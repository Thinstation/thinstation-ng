"""Local storage discovery and explicitly confirmed, grow-only maintenance.

Read-only status does not run resize commands. No partition editing, shrinking,
formatting, or data migration is supported by this API.
"""
import argparse
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time

BASE = Path('/var/prstnt/mcp-appliance')
RUN = Path('/run/mcp-appliance/storage')
UNIT = 'mcp-storage-operation.service'
TOOLS = ('systemd-run', 'lsblk', 'findmnt', 'pvs', 'vgs', 'lvs', 'pvresize',
         'lvextend', 'vgcfgbackup', 'resize2fs', 'dumpe2fs', 'xfs_info', 'xfs_growfs')
READ_TOOLS = {'lsblk', 'findmnt', 'pvs', 'vgs', 'lvs', 'dumpe2fs', 'xfs_info'}
NAME = re.compile(r'[A-Za-z0-9_+][A-Za-z0-9_.+-]{0,126}')


def number(value):
    try:
        result = Decimal(str(value).strip())
        if not result.is_finite() or result < 0 or result > 2 ** 63 - 1 or result != int(result):
            raise ValueError()
        return int(result)
    except (InvalidOperation, TypeError, OverflowError, ValueError):
        raise ValueError('Invalid storage size.') from None


def invoke(name, args, timeout=20):
    binary = shutil.which(name)
    if not binary:
        raise ValueError('Required storage tool is unavailable: ' + name)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LVM_', 'PYTHON'))}
    env.update(LC_ALL='C', LANG='C')
    return subprocess.run([binary, *args], capture_output=True, text=True,
                          timeout=timeout, env=env, check=False)


def read_command(name, args):
    if name not in READ_TOOLS:
        raise ValueError('Read-only storage command required.')
    result = invoke(name, args)
    if result.returncode:
        raise ValueError(name + ' could not inspect local storage.')
    return result.stdout


def flatten(rows):
    result = {}
    def visit(row, parent=None):
        if not isinstance(row, dict):
            raise ValueError('Invalid block-device report.')
        item = {k: v for k, v in row.items() if k != 'children'}
        item['parent_path'] = parent
        path = item.get('path')
        if path:
            item['size'] = number(item.get('size') or 0)
            if path in result and result[path].get('parent_path') != parent:
                result[path]['multiple_parents'] = True
            else:
                result[path] = item
        for child in row.get('children') or []:
            visit(child, path)
    for row in rows:
        visit(row)
    return list(result.values())


def lvm_report(tool, section, fields):
    # These report commands do not allocate/change volumes. Do not use
    # --readonly: it suppresses kernel state needed to identify active LVs.
    doc = json.loads(read_command(tool, ['--nohints', '--reportformat', 'json',
                     '--units', 'b', '--nosuffix', '-o', fields]))
    result = []
    for report in doc.get('report', []):
        for row in report.get(section, []):
            item = {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
            if item not in result:
                result.append(item)
    return result


def filesystem_bytes(device, target, fstype):
    if fstype == 'ext4':
        text = read_command('dumpe2fs', ['-h', device])
        count = re.search(r'^Block count:\s*(\d+)\s*$', text, re.M)
        size = re.search(r'^Block size:\s*(\d+)\s*$', text, re.M)
        return int(count[1]) * int(size[1]) if count and size else None
    if fstype == 'xfs':
        text = read_command('xfs_info', [target])
        match = re.search(r'data\s*=.*?bsize=(\d+)\s+blocks=(\d+)', text)
        return int(match[1]) * int(match[2]) if match else None
    return None


def snapshot():
    warnings = []
    tools = {name: bool(shutil.which(name)) for name in TOOLS}
    block = json.loads(read_command('lsblk', ['--json', '--bytes', '--output',
        'NAME,KNAME,PATH,TYPE,SIZE,FSTYPE,MOUNTPOINTS,PKNAME,RO,RM,MAJ:MIN,UUID,MODEL,SERIAL']))
    devices = flatten(block.get('blockdevices', []))
    doc = json.loads(read_command('findmnt', ['--json', '--list', '--output',
        'TARGET,SOURCE,FSTYPE,OPTIONS,FSROOT,MAJ:MIN']))
    mounts = []
    for row in doc.get('filesystems', []):
        item = dict(row)
        match = next((d for d in devices if d.get('maj:min') == row.get('maj:min')), None)
        item.update(device=match.get('path') if match else None,
                    device_bytes=number(match.get('size') or 0) if match else 0,
                    uuid=match.get('uuid') if match else None, fs_bytes=None)
        try:
            usage = os.statvfs(row['target'])
            item.update(total_bytes=usage.f_blocks * usage.f_frsize,
                        used_bytes=(usage.f_blocks - usage.f_bfree) * usage.f_frsize,
                        available_bytes=usage.f_bavail * usage.f_frsize,
                        reserved_bytes=(usage.f_bfree - usage.f_bavail) * usage.f_frsize)
        except OSError:
            item.update(total_bytes=None, used_bytes=None, available_bytes=None, reserved_bytes=None)
        if match and row.get('fsroot') == '/' and row.get('fstype') in ('ext4', 'xfs'):
            try:
                item['fs_bytes'] = filesystem_bytes(match['path'], row['target'], row['fstype'])
            except (OSError, ValueError, subprocess.SubprocessError):
                item['size_warning'] = 'Filesystem geometry cannot be verified; growth is unavailable.'
        mounts.append(item)
    lvm = {'available': False, 'pvs': [], 'vgs': [], 'lvs': []}
    if all(tools[t] for t in ('pvs', 'vgs', 'lvs')):
        try:
            lvm['pvs'] = lvm_report('pvs', 'pv', 'pv_name,pv_uuid,vg_name,vg_uuid,pv_size,pv_free,dev_size,pe_start,pv_pe_count,pv_attr')
            lvm['vgs'] = lvm_report('vgs', 'vg', 'vg_name,vg_uuid,vg_size,vg_free,vg_extent_size,vg_extent_count,vg_free_count,vg_attr')
            lvm['lvs'] = lvm_report('lvs', 'lv', 'lv_name,lv_uuid,lv_path,vg_name,vg_uuid,lv_size,lv_attr,segtype,origin,pool_lv,lv_kernel_major,lv_kernel_minor')
            lvm['available'] = True
        except (OSError, ValueError, subprocess.SubprocessError):
            warnings.append('LVM discovery failed. LVM changes are disabled; no empty-volume assumption was made.')
    else:
        warnings.append('LVM tools are not installed in this image. LVM controls are unavailable.')
    return {'checked_at': int(time.time()), 'devices': devices, 'mounts': mounts,
            'lvm': lvm, 'tools': tools, 'warnings': warnings,
            'scope': 'This appliance only. Grow-only: no partition resizing, shrinking, formatting, or moving data.'}


def fingerprint(state):
    keys = ('path', 'parent_path', 'type', 'size', 'ro', 'rm', 'fstype', 'uuid', 'maj:min', 'multiple_parents', 'serial')
    devices = sorted([{k: d.get(k) for k in keys} for d in state['devices']], key=lambda x: x['path'])
    keys = ('target', 'source', 'fstype', 'options', 'fsroot', 'maj:min', 'device', 'uuid', 'fs_bytes')
    mounts = sorted([{k: m.get(k) for k in keys} for m in state['mounts'] if m.get('device')], key=lambda x: (x['target'], x['source']))
    return hashlib.sha256(json.dumps({'devices': devices, 'mounts': mounts, 'lvm': state['lvm']}, sort_keys=True).encode()).hexdigest()


def device_for(state, path):
    if not isinstance(path, str) or not path.startswith('/dev/') or '..' in Path(path).parts or any(c.isspace() or ord(c) < 32 for c in path):
        raise ValueError('Invalid local block-device path.')
    rows = [d for d in state['devices'] if d.get('path') == path]
    if len(rows) != 1:
        raise ValueError('Storage device is missing or ambiguous; refresh discovery.')
    row = rows[0]
    if row.get('multiple_parents') and row.get('type') != 'lvm':
        raise ValueError('Ambiguous block-device topology.')
    if row.get('ro') or row.get('rm') or row.get('type') not in ('disk', 'part', 'lvm'):
        raise ValueError('Only writable non-removable disks, partitions and ordinary LVM volumes are supported.')
    if row.get('type') == 'part':
        parent = device_for(state, row.get('parent_path'))
        if parent.get('type') != 'disk':
            raise ValueError('Layered partition storage is not supported.')
    return row


def group_for(state, name):
    if not state['lvm']['available'] or not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError('Verified LVM discovery is required.')
    rows = [v for v in state['lvm']['vgs'] if v.get('vg_name') == name]
    if len(rows) != 1:
        raise ValueError('Volume group is missing or ambiguous.')
    group = rows[0]
    attr = group.get('vg_attr', '')
    if len(attr) < 6 or attr[0] != 'w' or attr[2:4] != '--' or attr[5] != '-':
        raise ValueError('Read-only, exported, partial, clustered or shared volume groups are not supported.')
    pvs = [p for p in state['lvm']['pvs'] if p.get('vg_name') == name]
    if not pvs:
        raise ValueError('Volume group physical volumes could not be verified.')
    for pv in pvs:
        device = device_for(state, pv['pv_name'])
        if device['type'] not in ('disk', 'part') or device.get('fstype') != 'LVM2_member' or 'm' in pv.get('pv_attr', ''):
            raise ValueError('LVM on encryption, RAID, missing or other layered devices is not supported.')
    return group


def mount_for(state, target):
    if not isinstance(target, str) or not target.startswith('/') or any(ord(c) < 32 for c in target):
        raise ValueError('Select an existing mount point.')
    rows = [m for m in state['mounts'] if m.get('target') == target]
    if len(rows) != 1:
        raise ValueError('Mount point is missing or ambiguous.')
    mount = rows[0]
    if not mount.get('device') or mount.get('fstype') not in ('ext4', 'xfs') or mount.get('fsroot') != '/' or 'rw' not in mount.get('options', '').split(','):
        raise ValueError('Only writable ext4/XFS filesystem mounts are supported; not bind, RAM, overlay or network mounts.')
    if not mount.get('uuid') or not mount.get('fs_bytes'):
        raise ValueError('Filesystem UUID and exact size must be verified before growth.')
    if len([m for m in state['mounts'] if m.get('maj:min') == mount.get('maj:min')]) != 1:
        raise ValueError('This filesystem has multiple mounts; automatic growth is disabled.')
    device = device_for(state, mount['device'])
    lv = None
    if device['type'] == 'lvm':
        rows = [v for v in state['lvm']['lvs'] if str(v.get('lv_kernel_major')) + ':' + str(v.get('lv_kernel_minor')) == mount['maj:min']]
        if len(rows) != 1:
            raise ValueError('Logical volume identity cannot be verified.')
        lv = rows[0]
        attr = lv.get('lv_attr', '')
        if lv.get('segtype') != 'linear' or lv.get('origin') or lv.get('pool_lv') or len(attr) < 5 or attr[0:2] != '-w' or attr[4] != 'a':
            raise ValueError('Only active ordinary linear LVM volumes are supported; not thin, snapshot, cached, RAID or mirrored volumes.')
        group_for(state, lv['vg_name'])
        if not NAME.fullmatch(lv['lv_name']) or lv['lv_path'] != '/dev/' + lv['vg_name'] + '/' + lv['lv_name']:
            raise ValueError('Logical volume path cannot be verified.')
        if number(lv['lv_size']) != number(device['size']):
            raise ValueError('Logical-volume metadata and kernel size disagree; rescan before growth.')
    return mount, device, lv


def resize_step(state, mount):
    tool = 'resize2fs' if mount['fstype'] == 'ext4' else 'xfs_growfs'
    if not state['tools'].get(tool):
        raise ValueError('Filesystem growth tool is missing: ' + tool)
    return {'tool': tool, 'args': [mount['device']] if tool == 'resize2fs' else ['-d', mount['target']],
            'description': 'Grow the ' + mount['fstype'] + ' filesystem at ' + mount['target'], 'mutation': True}


def build_plan(state, request):
    if not isinstance(request, dict) or set(request) - {'operation', 'target', 'add_bytes'}:
        raise ValueError('Unknown storage plan field.')
    op, target = request.get('operation'), request.get('target')
    steps, details = [], {}
    warning = 'Growth cannot be automatically undone. Keep a current backup. No filesystem will be shrunk.'
    if op in ('grow-filesystem', 'allocate'):
        mount, device, lv = mount_for(state, target)
        binding = {k: mount[k] for k in ('target', 'device', 'uuid', 'maj:min', 'fstype', 'fsroot')}
        if op == 'grow-filesystem':
            if number(device['size']) - mount['fs_bytes'] < 1024 * 1024:
                raise ValueError('No verified unused capacity exists inside this device. Enlarge its backing disk or logical volume first.')
            details = {'current_bytes': mount['fs_bytes'], 'target_bytes': number(device['size']), 'added_bytes': number(device['size']) - mount['fs_bytes']}
            phrase = 'GROW ' + target
        else:
            if not lv:
                raise ValueError('This mount is not on LVM. Space cannot be allocated to it from a volume group.')
            group = group_for(state, lv['vg_name'])
            added = request.get('add_bytes')
            if type(added) is not int or not 1 <= added <= 2 ** 53 - 1:
                raise ValueError('Specify a positive integer number of bytes to allocate.')
            extent, old_size = number(group['vg_extent_size']), number(lv['lv_size'])
            if not extent or old_size % extent:
                raise ValueError('LVM extent geometry is not supported.')
            extents = (added + extent - 1) // extent
            if extents > number(group['vg_free_count']):
                raise ValueError('The volume group does not have enough unallocated space.')
            for tool in ('lvextend', 'vgcfgbackup'):
                if not state['tools'].get(tool):
                    raise ValueError('Required LVM tool is unavailable: ' + tool)
            total = old_size // extent + extents
            steps = [{'tool': 'vgcfgbackup', 'args': [group['vg_name']], 'description': 'Back up volume group metadata', 'mutation': False},
                     {'tool': 'lvextend', 'args': ['--extents', str(total), lv['lv_path']], 'description': 'Allocate ' + str(extents) + ' extents from ' + group['vg_name'], 'mutation': True}]
            details = {'current_bytes': old_size, 'filesystem_bytes': mount['fs_bytes'], 'target_bytes': total * extent, 'added_bytes': extents * extent,
                       'vg': group['vg_name'], 'vg_remaining_bytes': (number(group['vg_free_count']) - extents) * extent}
            phrase = 'ALLOCATE ' + target
        steps.append(resize_step(state, mount))
    elif op == 'grow-pv':
        device = device_for(state, target)
        rows = [p for p in state['lvm']['pvs'] if p['pv_name'] == target]
        if len(rows) != 1 or device['type'] not in ('disk', 'part'):
            raise ValueError('Select an existing physical volume on a disk or partition.')
        pv = rows[0]
        group = group_for(state, pv['vg_name'])
        extent = number(group['vg_extent_size'])
        if number(device['size']) < number(pv['pv_size']) or not extent:
            raise ValueError('The physical volume device is smaller than expected.')
        potential = (number(device['size']) - number(pv['pe_start'])) // extent - number(pv['pv_pe_count'])
        if potential <= 0:
            raise ValueError('No new PV extents are visible. A containing partition must be expanded separately first.')
        if not state['tools'].get('pvresize') or not state['tools'].get('vgcfgbackup'):
            raise ValueError('LVM growth tools are not installed.')
        binding = {'device': target, 'uuid': device.get('uuid'), 'maj:min': device['maj:min'], 'pv_uuid': pv['pv_uuid']}
        steps = [{'tool': 'vgcfgbackup', 'args': [group['vg_name']], 'description': 'Back up volume group metadata', 'mutation': False},
                 {'tool': 'pvresize', 'args': [target], 'description': 'Make enlarged-device capacity available to ' + group['vg_name'], 'mutation': True}]
        details = {'current_bytes': number(pv['pv_size']), 'device_bytes': number(device['size']), 'estimated_added_bytes': potential * extent, 'vg': group['vg_name']}
        phrase = 'EXPAND ' + target
        warning += ' This does not resize partitions or assign the new space to a mount.'
    else:
        raise ValueError('Select grow filesystem, grow physical volume, or allocate space to an LVM mount.')
    return {'request': request, 'fingerprint': fingerprint(state), 'binding': binding,
            'steps': steps, 'details': details, 'confirmation': phrase, 'warning': warning}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 131072:
            raise ValueError('Unsafe storage control file.')
        return json.load(stream)


def annotate(state):
    for mount in state['mounts']:
        if not mount.get('device'):
            continue
        mount['grow'] = {'available': False}
        mount['allocation'] = {'available': False}
        try:
            plan = build_plan(state, {'operation': 'grow-filesystem', 'target': mount['target']})
            mount['grow'] = {'available': True, **plan['details']}
        except ValueError as exc:
            mount['grow']['reason'] = str(exc)
        try:
            _, _, lv = mount_for(state, mount['target'])
            if not lv:
                raise ValueError('This filesystem is not on LVM.')
            vg = group_for(state, lv['vg_name'])
            if number(vg['vg_free_count']) == 0:
                raise ValueError('No unallocated space remains in this volume group.')
            build_plan(state, {'operation': 'allocate', 'target': mount['target'], 'add_bytes': 1})
            mount['allocation'] = {'available': True, 'vg': vg['vg_name'], 'free_bytes': number(vg['vg_free_count']) * number(vg['vg_extent_size'])}
        except ValueError as exc:
            mount['allocation']['reason'] = str(exc)
    state['pv_actions'] = []
    for pv in state['lvm']['pvs']:
        row = {'device': pv['pv_name'], 'available': False}
        try:
            plan = build_plan(state, {'operation': 'grow-pv', 'target': pv['pv_name']})
            row.update(available=True, **plan['details'])
        except ValueError as exc:
            row['reason'] = str(exc)
        state['pv_actions'].append(row)
    return state


class Storage:
    def __init__(self, base=BASE, runtime=RUN, scanner=snapshot):
        self.base, self.runtime, self.scan = Path(base), Path(runtime), scanner
        self.state = self.base / 'state/storage-job.json'

    @contextmanager
    def lock(self, wait=False):
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.runtime.stat()
        if self.runtime.is_symlink() or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise ValueError('Unsafe storage runtime directory.')
        fd = os.open(self.runtime / 'operation.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            deadline = time.monotonic() + (30 if wait else 0)
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError('A storage operation is already running.') from None
                    time.sleep(.1)
            yield

    def job(self):
        if not self.state.exists():
            return {'state': 'idle', 'message': 'No storage changes have been requested.'}
        row = load_private(self.state)
        if row.get('state') in ('queued', 'running') and time.time() - row.get('updated_at', 0) > 1860:
            row = {**row, 'state': 'interrupted', 'message': 'The storage worker did not complete. Inspect storage before retrying; capacity may already have increased.'}
        return row

    def record(self, row):
        row['updated_at'] = int(time.time())
        atomic_json(self.state, row)
        return row

    def status(self):
        return {**annotate(self.scan()), 'job': self.job()}

    def prepare(self, body, actor):
        if not isinstance(actor, str) or not actor:
            raise ValueError('Administrator identity is required.')
        with self.lock():
            if self.job().get('state') in ('queued', 'running'):
                raise ValueError('A storage operation is already pending.')
            plan = build_plan(self.scan(), body)
            plan.update(id=secrets.token_hex(16), actor=actor, expires=int(time.time()) + 300)
            atomic_json(self.runtime / (plan['id'] + '.plan'), plan)
            for path in self.runtime.glob('*.plan'):
                if path.stat().st_mtime < time.time() - 600:
                    path.unlink(missing_ok=True)
            return {'plan': plan, 'message': 'Preview only. No disk or filesystem has changed.'}

    def apply(self, body, actor):
        if not os.path.ismount(self.base.parent):
            raise ValueError('Persistent storage must be mounted before a resize can run.')
        if not isinstance(body, dict) or set(body) != {'plan_id', 'confirmation'}:
            raise ValueError('Submit the plan identifier and exact confirmation text.')
        identifier = body['plan_id']
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise ValueError('Invalid storage plan.')
        with self.lock():
            if self.job().get('state') in ('queued', 'running'):
                raise ValueError('A storage operation is already pending.')
            path = self.runtime / (identifier + '.plan')
            try:
                plan = load_private(path)
            except FileNotFoundError:
                raise ValueError('Plan expired or was already used. Preview again.') from None
            if plan['actor'] != actor or plan['expires'] <= time.time():
                raise ValueError('Plan expired or belongs to another administrator.')
            if body['confirmation'] != plan['confirmation']:
                raise ValueError('Type the exact confirmation text shown in the preview.')
            current = build_plan(self.scan(), plan['request'])
            if any(current[k] != plan[k] for k in current):
                raise ValueError('Storage changed after the preview. Refresh and preview again.')
            os.replace(path, self.runtime / (identifier + '.queued'))
            self.record({'id': identifier, 'state': 'queued', 'message': 'Confirmed storage operation queued.', 'steps': [], 'request': plan['request']})
            try:
                result = invoke('systemd-run', ['--quiet', '--collect', '--no-block', '--unit=' + UNIT,
                    '--property=Type=oneshot', '--property=UMask=0077', '--property=TimeoutStartSec=30min',
                    '/usr/bin/python3', '-E', str(Path(__file__).resolve()), '--run', identifier])
            except (OSError, ValueError, subprocess.SubprocessError):
                self.record({'id': identifier, 'state': 'interrupted', 'message': 'Worker launch could not be verified. Inspect the storage service before retrying.', 'steps': []})
                raise ValueError('Worker launch could not be verified. Inspect System / Storage before retrying.') from None
            if result.returncode:
                self.record({'id': identifier, 'state': 'failed', 'message': 'Storage worker could not start. No storage commands ran.', 'steps': []})
                raise ValueError('Storage worker could not start. Preview again after checking the service journal.')
            return {'ok': True, 'job': self.job()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run')
    args = parser.parse_args()
    manager = Storage()
    if args.run:
        from mcp_storage_worker import run
        raise SystemExit(run(manager, args.run))
    print(json.dumps(manager.status(), indent=2))
