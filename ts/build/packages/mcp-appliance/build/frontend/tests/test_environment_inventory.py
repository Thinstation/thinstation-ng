"""Inventory fixtures only: no package managers, mounts or environment mutations."""
import importlib.util
import sys
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[3]/'usr/bin/mcp_environments.py'
sys.path.insert(0,str(SOURCE.parent))
spec=importlib.util.spec_from_file_location('environment_inventory',SOURCE)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class InventoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)/'chroots';self.state=Path(self.tmp.name)/'jobs';self.manifests=Path(self.tmp.name)/'manifests'
  for path in (self.root,self.state,self.manifests):path.mkdir()
  for key,value in [('ROOT',self.root),('STATE',self.state),('MANIFESTS',self.manifests)]:
   obj=patch.object(module,key,value);obj.start();self.addCleanup(obj.stop)
  obj=patch.object(module.Environments,'sources',return_value={});obj.start();self.addCleanup(obj.stop)
  self.api=module.Environments()
 def env(self,name='media-f44',manager='dnf'):
  root=self.root/name;(root/'usr/bin').mkdir(parents=True);(root/'etc').mkdir()
  (root/'etc/os-release').write_text('PRETTY_NAME="Fixture OS"')
  if manager:(root/'usr/bin'/manager).write_text('fixture')
  return root
 def job(self,ident='a'*32,**values):
  data={'id':ident,'name':'media-f44','action':'check','state':'completed','created_at':'2026-10-15T12:00:00Z',**values}
  (self.state/(ident+'.json')).write_text(json.dumps(data));return data
 def test_internal_directories_are_not_installed(self):
  self.env();self.env('.stage-'+'a'*32);self.env('.previous-'+'b'*32)
  data=self.api.status();self.assertEqual(len(data['installed']),1);self.assertEqual(len(data['staging']),2)
 def test_symlink_directory_is_not_followed(self):
  self.env();(self.root/'alias').symlink_to(self.root/'media-f44');self.assertEqual(len(self.api.status()['installed']),1)
 def test_staging_metadata_matches_job(self):
  self.env('.stage-'+'a'*32);self.job(state='failed')
  row=self.api.status()['staging'][0];self.assertEqual(row['state'],'failed');self.assertEqual(row['environment'],'media-f44')
 def test_untracked_staging_is_not_claimed_failed(self):
  self.env('.stage-'+'a'*32);self.assertIsNone(self.api.status()['staging'][0]['state'])
 def test_definition_enables_redeploy(self):
  self.env();(self.manifests/'media-f44.json').write_text('{"packages":["ffmpeg"]}')
  self.assertTrue(self.api.status()['installed'][0]['rebuild_available'])
 def test_missing_and_malformed_definitions_disable_redeploy(self):
  self.env()
  for value in ('null','[]','{"packages":[]}','{"packages":["--unsafe"]}'):
   (self.manifests/'media-f44.json').write_text(value);self.assertFalse(self.api.status()['installed'][0]['rebuild_available'])
 def test_check_result_exposed_independently(self):
  self.env();self.job(updates_available=True);row=self.api.status()['installed'][0]
  self.assertTrue(row['updates_available']);self.assertEqual(row['operation_state'],'completed')
 def test_subsequent_mutation_invalidates_check(self):
  self.env();self.job(updates_available=False);self.job('b'*32,action='update',state='failed',created_at='2026-10-15T13:00:00Z')
  row=self.api.status()['installed'][0];self.assertIsNone(row['last_checked']);self.assertIsNone(row['updates_available'])
 def test_recent_jobs_omit_logs_owners_and_error_payloads(self):
  self.env();self.job(owner='private-user',log_tail='not inventory data',error='not inventory data')
  row=self.api.status()['jobs'][0];self.assertNotIn('owner',row);self.assertNotIn('log_tail',row);self.assertNotIn('error',row)
 def test_corrupt_job_metadata_does_not_break_inventory(self):
  self.env();(self.state/'bad.json').write_text('null');(self.state/'invalid.json').write_text('{')
  self.assertEqual(len(self.api.status()['installed']),1)


 def test_worker_recheck_survives_inventory_reload(self):
  self.env();self.job(action='update',checked_at='2026-10-16T01:00:00Z',check_state='succeeded',updates_available=False,update_count=0)
  row=self.api.status()['installed'][0]
  self.assertEqual(row['last_checked'],'2026-10-16T01:00:00Z');self.assertFalse(row['updates_available']);self.assertEqual(row['update_count'],0)
 def test_failed_check_not_presented_as_unchecked(self):
  self.env();self.job(state='failed',check_state='failed',check_attempted_at='2026-10-16T01:00:00Z')
  row=self.api.status()['installed'][0];self.assertEqual(row['check_state'],'failed');self.assertTrue(row['last_check_attempt']);self.assertIsNone(row['updates_available'])
 def test_deletion_token_exposed_for_supported_directory(self):
  self.env();row=self.api.status()['installed'][0];self.assertTrue(row['delete_available']);self.assertEqual(len(row['delete_token']),64)
if __name__=='__main__':unittest.main()
