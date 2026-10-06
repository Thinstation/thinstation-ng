import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_inventory as module

class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.old=self.root/'etc/hosts.json';self.old.parent.mkdir()
        self.data={'hosts':{'ad':{'address':'dc.example.test','hostname':'dc.example.test','username':'operator','platform':'windows','identity_file':''}},'groups':{}}
        self.old.write_text(json.dumps(self.data))
        self.store=module.Inventory(self.root/'persistent/config/hosts.json',self.old)
    def tearDown(self):self.tmp.cleanup()
    def test_existing_host_migrates_without_loss(self):
        self.assertEqual(json.loads(self.store.read()['value']),self.data)
        self.assertEqual(self.store.path.stat().st_mode&0o777,0o600)
    def test_new_install_empty_inventory(self):
        self.old.unlink();self.assertEqual(json.loads(self.store.read()['value']),{'hosts':{},'groups':{}})
    def test_persistent_wins_after_reboot(self):
        self.store.ensure();self.old.write_text('{}')
        fresh=module.Inventory(self.store.path,self.old)
        self.assertEqual(json.loads(fresh.read()['value']),self.data)
    def test_save_then_read_includes_new_host(self):
        revision=self.store.read()['revision'];self.data['hosts']['web']={**self.data['hosts']['ad'],'platform':'linux','address':'192.0.2.10'}
        result=self.store.save(json.dumps(self.data),revision)
        self.assertTrue(result['changed']);self.assertIn('web',json.loads(result['value'])['hosts'])
        self.assertNotEqual(revision,result['revision'])
    def test_identical_save_does_not_require_restart(self):
        self.assertFalse(self.store.save(json.dumps(self.data))['changed'])
    def test_stale_save_rejected_without_overwriting(self):
        revision=self.store.read()['revision'];new={**self.data,'groups':{'servers':{'hosts':['ad']}}}
        self.store.save(json.dumps(new),revision)
        with self.assertRaisesRegex(ValueError,'another session'):self.store.save(json.dumps(self.data),revision)
        self.assertEqual(json.loads(self.store.read()['value']),new)
    def test_malformed_inventory_never_overwrites(self):
        before=self.store.read()['value']
        for raw in ('[]','null','{"hosts":[]}','{"groups":{"bad":{"hosts":["missing"]}}}','{bad'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):self.store.save(raw)
        self.assertEqual(self.store.read()['value'],before)
    def test_prototype_names_rejected(self):
        for name in ('__proto__','prototype','constructor'):
            data={'hosts':{name:self.data['hosts']['ad']}}
            with self.subTest(name=name),self.assertRaises(ValueError):self.store.save(json.dumps(data))
    def test_unknown_group_fields_preserved(self):
        self.data['groups']={'servers':{'hosts':['ad'],'credential_policy':'keep'}}
        self.assertEqual(json.loads(self.store.save(json.dumps(self.data))['value']),self.data)
    def test_incomplete_host_rejected(self):
        for field in ('address','platform'):
            data=json.loads(json.dumps(self.data));data['hosts']['ad'].pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError):self.store.save(json.dumps(data))
    def test_username_not_required(self):
        self.data['hosts']['ad'].pop('username')
        result=self.store.save(json.dumps(self.data))
        self.assertNotIn('username',json.loads(result['value'])['hosts']['ad'])
    def test_only_active_runtime_restarted(self):
        results=[subprocess.CompletedProcess([],0,'active\n',''),subprocess.CompletedProcess([],0,'','')]
        with patch.object(module.subprocess,'run',side_effect=results) as run:
            self.assertIn('restarted',module.apply_runtime())
        self.assertEqual(run.call_args.args[0],['/usr/bin/systemctl','try-restart','mcp-runtime.service'])
    def test_stopped_runtime_is_not_started(self):
        with patch.object(module.subprocess,'run',return_value=subprocess.CompletedProcess([],3,'inactive\n','')) as run:
            self.assertIn('Start',module.apply_runtime());self.assertEqual(run.call_count,1)
    def test_restart_failure_does_not_report_save_failure(self):
        with patch.object(module.subprocess,'run',side_effect=OSError):self.assertIn('Inventory saved',module.apply_runtime())

if __name__=='__main__':unittest.main()
