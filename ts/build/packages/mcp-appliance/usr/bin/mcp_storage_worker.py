"""Execute only server-created, confirmed growth plans. Not a shell interface.

This module is inert on import. Production execution requires a queued plan
created by the administrator-only storage API, with a matching topology.
"""
import os
from pathlib import Path
import re
import stat
import subprocess
import time


def verify_binding(state, plan):
    from mcp_storage import device_for, group_for, mount_for
    target = plan['request']['target']
    if plan['request']['operation'] == 'grow-pv':
        device = device_for(state, target)
        rows = [p for p in state['lvm']['pvs'] if p['pv_name'] == target]
        if len(rows) != 1 or rows[0]['pv_uuid'] != plan['binding']['pv_uuid']:
            raise ValueError('Physical volume identity changed.')
        group_for(state, rows[0]['vg_name'])
        binding = {'device': target, 'uuid': device.get('uuid'), 'maj:min': device['maj:min'], 'pv_uuid': rows[0]['pv_uuid']}
    else:
        mount, device, _ = mount_for(state, target)
        binding = {k: mount[k] for k in ('target', 'device', 'uuid', 'maj:min', 'fstype', 'fsroot')}
    if binding != plan['binding']:
        raise ValueError('Storage identity changed after confirmation.')
    info = os.stat(device['path'])
    devno = str(os.major(info.st_rdev)) + ':' + str(os.minor(info.st_rdev))
    if not stat.S_ISBLK(info.st_mode) or devno != device['maj:min']:
        raise ValueError('Device node does not match the discovered block device.')


def run(manager, identifier):
    from mcp_storage import build_plan, load_private, mount_for, number, invoke
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Invalid storage job identifier.')
    with manager.lock(wait=True):
        queued = manager.runtime / (identifier + '.queued')
        active = manager.runtime / (identifier + '.running')
        if not queued.exists() or active.exists():
            raise ValueError('Storage job was already claimed or is unavailable.')
        plan = load_private(queued)
        job = manager.job()
        if job.get('id') != identifier or job.get('state') != 'queued':
            raise ValueError('Storage job is no longer queued.')
        os.replace(queued, active)
        job.update(state='running', message='Checking the confirmed storage plan.', steps=[], actor=plan['actor'])
        manager.record(job)
        possible_change = False
        try:
            if not os.path.ismount(manager.base.parent):
                raise ValueError('Persistent storage is not mounted.')
            current = build_plan(manager.scan(), plan['request'])
            if plan['expires'] <= time.time() or any(current[k] != plan[k] for k in current):
                raise ValueError('Storage changed or the plan expired before execution. Preview again.')
            verify_binding(manager.scan(), plan)
            backup_dir = manager.base / 'state/storage-backups' / identifier
            for step in current['steps']:
                before = manager.scan()
                verify_binding(before, plan)
                name, args = step['tool'], list(step['args'])
                if name not in ('vgcfgbackup', 'lvextend', 'pvresize', 'resize2fs', 'xfs_growfs'):
                    raise ValueError('Unexpected storage operation.')
                if name == 'vgcfgbackup':
                    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
                    args = ['--file', str(backup_dir / 'volume-group.conf'), *args]
                if name in ('lvextend', 'pvresize'):
                    refreshed = build_plan(before, plan['request'])
                    if refreshed['fingerprint'] != plan['fingerprint']:
                        raise ValueError('Storage allocation changed before the LVM command.')
                if name in ('resize2fs', 'xfs_growfs'):
                    mount, device, _ = mount_for(before, plan['request']['target'])
                    target_bytes = plan['details']['target_bytes']
                    if number(device['size']) != target_bytes:
                        raise ValueError('Backing-device size changed before filesystem growth.')
                    if mount['fs_bytes'] >= target_bytes:
                        raise ValueError('Filesystem geometry changed after confirmation; no resize was started.')
                row = {'description': step['description'], 'tool': name, 'state': 'running'}
                job['steps'].append(row)
                job['message'] = step['description']
                manager.record(job)
                possible_change = possible_change or step['mutation']
                result = invoke(name, args, timeout=1500 if name in ('resize2fs', 'xfs_growfs') else 120)
                row.update(exit_code=result.returncode, output=(result.stdout + result.stderr)[-6000:],
                           state='succeeded' if result.returncode == 0 else 'failed')
                manager.record(job)
                if result.returncode:
                    raise ValueError(name + ' failed. Read the operation result before taking further action.')
                if name == 'vgcfgbackup':
                    backup = backup_dir / 'volume-group.conf'
                    if not backup.is_file() or not backup.stat().st_size:
                        raise ValueError('Volume group metadata backup was not created.')
                    backup.chmod(0o600)
                    job['metadata_backup'] = str(backup)
                    manager.record(job)
                elif name == 'lvextend':
                    after = manager.scan()
                    verify_binding(after, plan)
                    _, device, _ = mount_for(after, plan['request']['target'])
                    if number(device['size']) != plan['details']['target_bytes']:
                        raise ValueError('Logical-volume growth could not be verified. The filesystem has not been resized.')
            after = manager.scan()
            verify_binding(after, plan)
            if plan['request']['operation'] == 'grow-pv':
                pv = next(p for p in after['lvm']['pvs'] if p['pv_name'] == plan['request']['target'])
                verified = number(pv['pv_size']) > plan['details']['current_bytes']
            else:
                mount, device, _ = mount_for(after, plan['request']['target'])
                verified = (mount['fs_bytes'] > plan['details'].get('filesystem_bytes', plan['details']['current_bytes'])
                            and 0 <= number(device['size']) - mount['fs_bytes'] < 1024 * 1024)
            if not verified:
                raise ValueError('Commands completed, but final capacity could not be verified. Inspect storage before retrying.')
            job.update(state='succeeded', message='Storage growth completed and the new capacity was verified.', capacity_verified=True)
            manager.record(job)
            return 0
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            job.update(state='needs-attention' if possible_change else 'failed',
                       message=str(exc) if isinstance(exc, ValueError) else 'Storage operation failed or timed out. Inspect the recorded steps and service journal.',
                       may_have_changed=possible_change,
                       recovery='No shrinking or automatic rollback was attempted. If the LV grew but its filesystem did not, refresh and preview Grow filesystem; do not repeat the allocation.')
            if job['steps'] and job['steps'][-1]['state'] == 'running':
                job['steps'][-1]['state'] = 'interrupted'
            manager.record(job)
            return 1
        finally:
            active.unlink(missing_ok=True)
