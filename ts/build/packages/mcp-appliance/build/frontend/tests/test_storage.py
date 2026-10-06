"""Storage tests use synthetic reports and mocked mutation commands only."""
import ast
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'usr/bin'))
import mcp_storage as storage
import mcp_storage_worker as worker
G = 1024 ** 3
E = 4 * 1024 ** 2


def fixture(lvm=True):
    disk = dict(path='/dev/vdb', type='disk', size=20*G, ro=False, rm=False, uuid='pv-disk', fstype='LVM2_member', **{'maj:min':'8:16'})
    device = dict(path='/dev/dm-0', type='lvm', size=4*G, ro=False, rm=False, uuid='fs-id', fstype='ext4', parent_path='/dev/vdb', **{'maj:min':'253:0'})
    mount = dict(target='/data', source='/dev/mapper/vg-data', device=device['path'], fstype='ext4', options='rw,relatime', fsroot='/', uuid='fs-id', fs_bytes=4*G, total_bytes=4*G, available_bytes=3*G, used_bytes=G, **{'maj:min':'253:0'})
    pv = dict(pv_name='/dev/vdb', pv_uuid='pv-id', vg_name='vg', vg_uuid='vg-id', pv_size=str(16*G), pv_free=str(12*G), pe_start='0', pv_pe_count='4096', pv_attr='a--')
    vg = dict(vg_name='vg', vg_uuid='vg-id', vg_size=str(16*G), vg_free=str(12*G), vg_extent_size=str(E), vg_extent_count='4096', vg_free_count='3072', vg_attr='wz--n-')
    lv = dict(lv_name='data', lv_uuid='lv-id', lv_path='/dev/vg/data', vg_name='vg', vg_uuid='vg-id', lv_size=str(4*G), lv_attr='-wi-a-----', segtype='linear', origin='', pool_lv='', lv_kernel_major='253', lv_kernel_minor='0')
    data = dict(devices=[disk,device], mounts=[mount], lvm=dict(available=True,pvs=[pv],vgs=[vg],lvs=[lv]), tools={t:True for t in storage.TOOLS}, warnings=[])
    if not lvm:
        disk.update(size=10*G, fstype='ext4', uuid='fs-id')
        data['devices']=[disk]
        mount.update(device='/dev/vdb', source='/dev/vdb', fs_bytes=8*G, **{'maj:min':'8:16'})
        data['lvm'].update(pvs=[],vgs=[],lvs=[])
    return data


class PlanTests(unittest.TestCase):
    def setUp(self): self.data=fixture()
    def plan(self, **extra):return storage.build_plan(self.data, {'operation':'allocate','target':'/data','add_bytes':E+1,**extra})
    def test_extent_rounding_and_absolute_size(self):
        p=self.plan();self.assertEqual(p['details']['added_bytes'],2*E)
        self.assertEqual(p['steps'][1]['args'],['--extents','1026','/dev/vg/data'])
        self.assertEqual(p['steps'][0]['tool'],'vgcfgbackup')
        self.assertEqual(p['steps'][-1]['tool'],'resize2fs')
    def test_vg_capacity_not_filesystem_free(self):
        self.data['mounts'][0]['available_bytes']=100*G
        with self.assertRaisesRegex(ValueError,'not have enough'):self.plan(add_bytes=13*G)
    def test_no_lvm_allocation_to_plain_mount(self):
        self.data=fixture(False)
        with self.assertRaisesRegex(ValueError,'not on LVM'):self.plan()
    def test_plain_grow(self):
        self.data=fixture(False);p=self.plan(operation='grow-filesystem')
        self.assertEqual(p['details']['added_bytes'],2*G);self.assertEqual(len(p['steps']),1)
    def test_xfs_grows_mount_not_device(self):
        self.data['mounts'][0]['fstype']='xfs'
        self.assertEqual(self.plan()['steps'][-1]['args'],['-d','/data'])
    def test_zero_negative_float_boolean_rejected(self):
        for value in [0,-1,1.5,True,'2',2**53]:
            with self.subTest(value=value),self.assertRaises(ValueError):self.plan(add_bytes=value)
    def test_missing_resize_tool(self):
        self.data['tools']['resize2fs']=False
        with self.assertRaisesRegex(ValueError,'missing'):self.plan()
    def test_missing_backup_tool(self):
        self.data['tools']['vgcfgbackup']=False
        with self.assertRaisesRegex(ValueError,'unavailable'):self.plan()
    def test_readonly_device(self):
        self.data['devices'][1]['ro']=True
        with self.assertRaises(ValueError):self.plan()
    def test_removable_device(self):
        self.data['devices'][0]['rm']=True
        with self.assertRaises(ValueError):self.plan()
    def test_readonly_mount(self):
        self.data['mounts'][0]['options']='ro'
        with self.assertRaises(ValueError):self.plan()
    def test_bind_mount(self):
        self.data['mounts'][0]['fsroot']='/subdirectory'
        with self.assertRaises(ValueError):self.plan()
    def test_duplicate_mount(self):
        self.data['mounts'].append({**self.data['mounts'][0],'target':'/other'})
        with self.assertRaisesRegex(ValueError,'multiple mounts'):self.plan()
    def test_unknown_geometry(self):
        self.data['mounts'][0]['fs_bytes']=None
        with self.assertRaisesRegex(ValueError,'exact size'):self.plan()
    def test_thin_snapshot_raid_not_supported(self):
        for segtype in ('thin','snapshot','raid1','cache','mirror'):
            self.data['lvm']['lvs'][0]['segtype']=segtype
            with self.subTest(segtype=segtype),self.assertRaises(ValueError):self.plan()
    def test_encrypted_pv_not_supported(self):
        self.data['devices'][0]['type']='crypt'
        with self.assertRaises(ValueError):self.plan()
    def test_partial_group_not_supported(self):
        self.data['lvm']['vgs'][0]['vg_attr']='wz-pn-'
        with self.assertRaises(ValueError):self.plan()
    def test_missing_pv_not_supported(self):
        self.data['lvm']['pvs'][0]['pv_attr']='a-m'
        with self.assertRaises(ValueError):self.plan()
    def test_metadata_kernel_disagreement(self):
        self.data['lvm']['lvs'][0]['lv_size']=str(8*G)
        with self.assertRaisesRegex(ValueError,'disagree'):self.plan()
    def test_no_filesystem_growth_without_device_growth(self):
        with self.assertRaisesRegex(ValueError,'No verified'):self.plan(operation='grow-filesystem')
    def test_pv_growth_is_separate(self):
        p=self.plan(operation='grow-pv',target='/dev/vdb')
        self.assertEqual([x['tool'] for x in p['steps']],['vgcfgbackup','pvresize'])
        self.assertEqual(p['details']['estimated_added_bytes'],4*G)
    def test_pv_cannot_shrink(self):
        self.data['devices'][0]['size']=8*G
        with self.assertRaisesRegex(ValueError,'smaller'):self.plan(operation='grow-pv',target='/dev/vdb')
    def test_partition_must_already_be_expanded(self):
        self.data['devices'][0]['size']=16*G
        with self.assertRaisesRegex(ValueError,'No new PV'):self.plan(operation='grow-pv',target='/dev/vdb')
    def test_arbitrary_commands_and_paths_rejected(self):
        for op,target in [('format','/dev/vdb'),('allocate','/not-mounted'),('grow-pv','/dev/../tmp/file')]:
            with self.subTest(op=op),self.assertRaises(ValueError):self.plan(operation=op,target=target)
        with self.assertRaises(ValueError):self.plan(command='anything')
    def test_usage_does_not_invalidate_geometry(self):
        old=storage.fingerprint(self.data);self.data['mounts'][0]['available_bytes']-=4096
        self.assertEqual(old,storage.fingerprint(self.data))
    def test_capacity_invalidates_geometry(self):
        old=storage.fingerprint(self.data);self.data['devices'][0]['size']+=G
        self.assertNotEqual(old,storage.fingerprint(self.data))
    def test_status_annotation_does_not_mutate_fingerprint(self):
        old=storage.fingerprint(self.data);storage.annotate(self.data)
        self.assertEqual(old,storage.fingerprint(self.data))
    def test_lvm_unavailable_is_not_empty(self):
        self.data['lvm']['available']=False
        self.assertFalse(storage.annotate(self.data)['mounts'][0]['allocation']['available'])
    def test_numbers_reject_unbounded_and_nonfinite(self):
        for value in ['nan','Infinity','-2','1.5','1e99999']:
            with self.subTest(value=value),self.assertRaises(ValueError):storage.number(value)
    def test_ext4_geometry_uses_block_count(self):
        with patch.object(storage,'read_command',return_value='Block count: 2048\nBlock size: 4096\n'):
            self.assertEqual(storage.filesystem_bytes('/dev/vdb','/data','ext4'),8388608)
    def test_xfs_geometry(self):
        with patch.object(storage,'read_command',return_value='data = bsize=4096 blocks=4096, imaxpct=25\n'):
            self.assertEqual(storage.filesystem_bytes('/dev/vdb','/data','xfs'),16777216)
    def test_read_report_cannot_invoke_mutation(self):
        with patch.object(storage,'invoke') as call,self.assertRaises(ValueError):storage.read_command('lvextend',[])
        call.assert_not_called()


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.data=fixture()
        self.api=storage.Storage(self.base/'persistent/appliance',self.base/'runtime',lambda:copy.deepcopy(self.data))
        self.mount_patch=patch.object(storage.os.path,'ismount',return_value=True);self.mount_patch.start()
    def tearDown(self):self.mount_patch.stop();self.tmp.cleanup()
    def preview(self):return self.api.prepare({'operation':'allocate','target':'/data','add_bytes':E},'admin')['plan']
    def queue(self,plan):
        with patch.object(storage,'invoke',return_value=subprocess.CompletedProcess([],0,'','')):
            return self.api.apply({'plan_id':plan['id'],'confirmation':plan['confirmation']},'admin')
    def test_preview_never_invokes_write_tool(self):
        with patch.object(storage,'invoke') as call:plan=self.preview()
        call.assert_not_called();self.assertEqual(self.api.job()['state'],'idle')
        self.assertEqual((self.api.runtime/(plan['id']+'.plan')).stat().st_mode&0o777,0o600)
    def test_typed_confirmation_required(self):
        p=self.preview()
        with self.assertRaisesRegex(ValueError,'exact confirmation'):self.api.apply({'plan_id':p['id'],'confirmation':'yes'},'admin')
    def test_actor_binding(self):
        p=self.preview()
        with self.assertRaisesRegex(ValueError,'another administrator'):self.api.apply({'plan_id':p['id'],'confirmation':p['confirmation']},'other')
    def test_expiry(self):
        p=self.preview();path=self.api.runtime/(p['id']+'.plan');p['expires']=0;storage.atomic_json(path,p)
        with self.assertRaisesRegex(ValueError,'expired'):self.queue(p)
    def test_geometry_changed_since_preview(self):
        p=self.preview();self.data['devices'][0]['size']+=G
        with self.assertRaisesRegex(ValueError,'changed'):self.queue(p)
    def test_queued_plan_is_single_use(self):
        p=self.preview();self.queue(p)
        self.assertFalse((self.api.runtime/(p['id']+'.plan')).exists())
        with self.assertRaisesRegex(ValueError,'pending'):self.queue(p)
    def test_unknown_apply_arguments(self):
        with self.assertRaises(ValueError):self.api.apply({'plan_id':'x','confirmation':'x','command':'x'},'admin')
    def test_unmounted_persistence_blocks_apply(self):
        p=self.preview()
        with patch.object(storage.os.path,'ismount',return_value=False),self.assertRaises(ValueError):self.queue(p)
    def test_worker_cannot_run_unconfirmed_plan(self):
        p=self.preview()
        with self.assertRaisesRegex(ValueError,'unavailable'):worker.run(self.api,p['id'])
    def fake_run(self,name,args,timeout=20):
        if name=='vgcfgbackup':Path(args[1]).write_text('fixture backup')
        elif name=='lvextend':
            size=int(args[1])*E;added=size-4*G
            self.data['devices'][1]['size']=size;self.data['lvm']['lvs'][0]['lv_size']=str(size)
            self.data['lvm']['vgs'][0]['vg_free_count']=str(3072-added//E)
            self.data['lvm']['vgs'][0]['vg_free']=str(12*G-added)
        elif name=='resize2fs':self.data['mounts'][0]['fs_bytes']=self.data['devices'][1]['size']
        return subprocess.CompletedProcess([],0,'fixture output','')
    def test_success_with_fake_executor(self):
        p=self.preview();self.queue(p)
        with patch.object(worker,'verify_binding'),patch.object(storage,'invoke',side_effect=self.fake_run):self.assertEqual(worker.run(self.api,p['id']),0)
        self.assertEqual(self.api.job()['state'],'succeeded');self.assertTrue(self.api.job()['capacity_verified'])
        self.assertTrue(Path(self.api.job()['metadata_backup']).is_file())
    def test_partial_failure_no_shrink_no_double_allocation(self):
        p=self.preview();self.queue(p)
        def fail(name,args,timeout=20):return subprocess.CompletedProcess([],1,'','fixture error') if name=='resize2fs' else self.fake_run(name,args,timeout)
        with patch.object(worker,'verify_binding'),patch.object(storage,'invoke',side_effect=fail) as calls:self.assertEqual(worker.run(self.api,p['id']),1)
        self.assertEqual(self.api.job()['state'],'needs-attention');self.assertTrue(self.api.job()['may_have_changed'])
        self.assertNotIn('lvreduce',[c.args[0] for c in calls.call_args_list])
        with self.assertRaises(ValueError):worker.run(self.api,p['id'])
        next_plan=storage.build_plan(self.data,{'operation':'grow-filesystem','target':'/data'})
        self.assertEqual([s['tool'] for s in next_plan['steps']],['resize2fs'])
    def test_failed_backup_prevents_growth(self):
        p=self.preview();self.queue(p)
        with patch.object(worker,'verify_binding'),patch.object(storage,'invoke',return_value=subprocess.CompletedProcess([],1,'','backup failed')) as calls:
            self.assertEqual(worker.run(self.api,p['id']),1)
        self.assertEqual(calls.call_count,1);self.assertFalse(self.api.job()['may_have_changed'])
    def test_stale_worker_rechecks(self):
        p=self.preview();self.queue(p);self.data['devices'][0]['size']+=G
        with patch.object(storage,'invoke') as call:self.assertEqual(worker.run(self.api,p['id']),1)
        call.assert_not_called()
    def test_tampered_plan_steps_rejected(self):
        p=self.preview();self.queue(p);path=self.api.runtime/(p['id']+'.queued');row=storage.load_private(path);row['steps'][0]['tool']='unexpected';storage.atomic_json(path,row)
        with patch.object(storage,'invoke') as call:self.assertEqual(worker.run(self.api,p['id']),1)
        call.assert_not_called()
    def test_device_identity_checked(self):
        p=self.preview()
        with patch.object(worker.os,'stat',return_value=type('Info',(),{'st_mode':0o100600,'st_rdev':os.makedev(253,0)})()),self.assertRaisesRegex(ValueError,'Device node'):worker.verify_binding(self.data,p)


class StorageAuthTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[3]/'usr/bin/mcp-operator-web'
        tree=ast.parse(path.read_text());definition=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='H')
        class Base: pass
        self.api=Mock();namespace={'legacy':{'H':Base},'storage':self.api,'urlparse':__import__('urllib.parse',fromlist=['urlparse']).urlparse,'json':json}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),str(path),'exec'),namespace)
        self.handler=namespace['H']();self.handler.path='/api/operator/storage/plan';self.handler.body=lambda:'{"operation":"allocate","target":"/data","add_bytes":4096}'
        self.handler.js=Mock();self.handler.user={'username':'admin','role':'admin'};self.handler.auth_kind='session';self.handler.auth=Mock(return_value=True)
    def test_unauthenticated_rejected(self):
        self.handler.auth.return_value=False;self.handler.do_POST();self.handler.js.assert_called_with(401,{'error':'Administrator sign-in required.'});self.api.prepare.assert_not_called()
    def test_bearer_token_rejected(self):
        self.handler.auth_kind='token';self.handler.do_POST();self.assertEqual(self.handler.js.call_args.args[0],403);self.api.prepare.assert_not_called()
    def test_nonadmin_rejected(self):
        self.handler.user['role']='user';self.handler.do_POST();self.assertEqual(self.handler.js.call_args.args[0],403);self.api.prepare.assert_not_called()
    def test_csrf_auth_and_actor_passed(self):
        self.handler.do_POST();self.handler.auth.assert_called_once_with(write=True);self.assertEqual(self.api.prepare.call_args.args[1],'admin')
    def test_get_only_inspects(self):
        self.handler.path='/api/operator/storage';self.handler.do_GET();self.api.status.assert_called_once();self.api.apply.assert_not_called()


if __name__=='__main__':unittest.main()
