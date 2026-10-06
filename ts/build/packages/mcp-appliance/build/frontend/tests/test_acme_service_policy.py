"""Synthetic policy tests: no real credentials, decryption, or service starts."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_acme_service as service

class ServicePolicyTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
  self.policy=service.ServicePolicy(self.base)
  self.cfg={'enabled':True,'automatic':True,'challenge':'dns-01','dns_provider':'active-directory','primary_domain':'mcp.example.test','alternative_names':[],'accept_terms':True,'credential':'test-ad','ad_host':'ad','ad_server':'dc.example.test','ad_zone':'example.test','directory_url':'https://ca.example.test/directory'}
  self.inventory={'hosts':{'ad':{'platform':'windows','hostname':'dc.example.test','address':'192.0.2.10'}},'groups':{'windows':{'hosts':['ad']}}}
  self.meta={'type':'active-directory','scopes':['acme'],'allowed_hosts':['group:windows']}
  self.secret=self.base/'vault/credentials/test-ad.cred';self.secret.parent.mkdir(parents=True);self.secret.write_bytes(b'synthetic-encrypted-placeholder');self.secret.chmod(0o600)
  self.metadata=self.base/'vault/metadata/test-ad.json';self.metadata.parent.mkdir(parents=True);self.metadata.write_text(json.dumps(self.meta));self.metadata.chmod(0o600)
 def tearDown(self):self.temp.cleanup()
 def approve(self):return self.policy.approve(self.cfg,self.inventory,self.policy.binding(self.cfg,self.inventory),'fixture-admin')
 def test_saved_settings_do_not_imply_permission(self):self.assertFalse(self.policy.status(self.cfg,self.inventory)['active'])
 def test_explicit_permission_is_persistent(self):
  self.approve();self.assertTrue(service.ServicePolicy(self.base).status(self.cfg,self.inventory)['active'])
 def test_approval_has_no_credential_material(self):
  self.approve();data=self.policy.path.read_bytes();self.assertNotIn(self.secret.read_bytes(),data);self.assertEqual(self.policy.path.stat().st_mode&0o777,0o600)
 def test_configuration_changes_invalidate(self):
  self.approve()
  for key,value in [('primary_domain','other.example.test'),('automatic',False),('enabled',False),('directory_url','https://other.example.test/'),('ad_zone','other.test')]:
   with self.subTest(key=key):self.assertFalse(self.policy.status({**self.cfg,key:value},self.inventory)['active'])
 def test_credential_rotation_invalidates(self):
  self.approve();self.secret.write_bytes(b'different-synthetic-placeholder');self.assertFalse(self.policy.status(self.cfg,self.inventory)['active'])
 def test_target_changes_invalidate(self):
  self.approve();other=copy.deepcopy(self.inventory);other['hosts']['ad']['address']='192.0.2.11';self.assertFalse(self.policy.status(self.cfg,other)['active'])
 def test_permission_removal_invalidates(self):
  self.approve();self.meta['scopes']=['ssh'];self.metadata.write_text(json.dumps(self.meta));self.assertFalse(self.policy.status(self.cfg,self.inventory)['active'])
 def test_stale_confirmation_rejected(self):
  with self.assertRaises(ValueError):self.policy.approve(self.cfg,self.inventory,'0'*64,'fixture-admin')
  self.assertFalse(self.policy.path.exists())
 def test_revoke_survives_recreation(self):
  row=self.approve();self.policy.revoke(row['id'],'fixture-admin');self.assertFalse(service.ServicePolicy(self.base).status(self.cfg,self.inventory)['active'])
 def test_wrong_revoke_id_does_not_remove(self):
  self.approve()
  with self.assertRaises(ValueError):self.policy.revoke('0'*32,'fixture-admin')
  self.assertTrue(self.policy.status(self.cfg,self.inventory)['active'])
 def test_requires_explicit_automatic_setting(self):
  for value in (False,'true',None):
   with self.subTest(value=value),self.assertRaises(ValueError):self.policy.binding({**self.cfg,'automatic':value},self.inventory)
 def test_missing_credential_fails_closed(self):
  self.approve();self.secret.unlink();self.assertFalse(self.policy.status(self.cfg,self.inventory)['active'])
 def test_symlink_approval_fails_closed(self):
  self.approve();original=self.policy.path.read_bytes();self.policy.path.unlink();target=self.base/'elsewhere';target.write_bytes(original);target.chmod(0o600);self.policy.path.symlink_to(target);self.assertFalse(self.policy.status(self.cfg,self.inventory)['active'])
 def test_unprotected_secret_file_rejected(self):
  self.secret.chmod(0o644)
  with self.assertRaises(ValueError):self.policy.binding(self.cfg,self.inventory)
 def test_arbitrary_command_rejected_before_process_inspection(self):
  with self.assertRaises(ValueError):service.worker_context(['/bin/sh','-c','true'],'ACME_CREDENTIAL_FILE')
 def test_arbitrary_scope_rejected_before_secret_access(self):
  with self.assertRaises(ValueError):service.authorize_worker('ssh','test-ad','ACME_CREDENTIAL_FILE',[])
 def test_audit_records_approval_and_revoke(self):
  row=self.approve();self.policy.revoke(row['id'],'fixture-admin');events=[json.loads(x)['event'] for x in (self.base/'log/vault-audit.jsonl').read_text().splitlines()];self.assertEqual(events,['acme_service_authorize','acme_service_revoke'])

if __name__=='__main__':unittest.main()
