import contextlib, io, json, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest.mock import patch
BIN=Path(__file__).resolve().parents[3]/'usr/bin'
sys.path.insert(0,str(BIN))
from mcp_login import login_name,password_identity,target_rank
class LoginTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.doc={'hosts':{'ad':{'address':'192.0.2.10','hostname':'dc.example.test','platform':'windows'}},'groups':{'controllers':{'hosts':['ad']}}}
  self.m=types.ModuleType('vault_fixture');source=(BIN/'mcp-vault-core').read_text().split('\nargs=sys.argv[1:]')[0];exec(compile(source,'vault-fixture','exec'),self.m.__dict__)
  for name,rel in {'BASE':'vault','CREDS':'vault/credentials','META':'vault/metadata','RUN':'run','LEASE':'run/lease.json','GRANTS':'run/grants','CRED_LEASES':'run/credential-leases','AUDIT':'log/audit','INVENTORY':'config/hosts.json','LEGACY_INVENTORY':'old.json','MATERIALIZED':'run/materialized'}.items():setattr(self.m,name,self.root/rel)
  self.m.ensure();self.m.INVENTORY.parent.mkdir();self.m.INVENTORY.write_text(json.dumps(self.doc))
 def tearDown(self):self.tmp.cleanup()
 def credential(self,name,ctype='ssh-key',targets=None,username='automation'):
  (self.m.CREDS/(name+'.cred')).write_text('ciphertext fixture');self.m.write_meta(name,{'name':name,'type':ctype,'username':username,'allowed_hosts':targets or [],'scopes':['ssh']})
 def capture(self,fn,*args):
  stream=io.StringIO()
  with contextlib.redirect_stdout(stream):fn(*args)
  return json.loads(stream.getvalue())
 def unlock(self,name='one',scope='ssh'):self.m.CRED_LEASES.mkdir(parents=True,exist_ok=True);self.m.CRED_LEASES.joinpath(name+'.json').write_text(json.dumps({'credential':name,'expires':time.time()+60,'scopes':[scope]}))
 def test_host_beats_group(self):
  self.credential('group',targets=['group:controllers']);self.credential('direct',targets=['host:ad'])
  self.assertEqual(self.capture(self.m.resolve_credential,'ad','ssh','ssh-login')['name'],'direct')
 def test_group_uses_new_persistent_inventory(self):
  self.m.LEGACY_INVENTORY.write_text('{}');self.credential('group',targets=['group:controllers'])
  self.assertEqual(self.capture(self.m.resolve_credential,'dc.example.test','ssh','ssh-login')['name'],'group')
 def test_bare_fqdn_matches_alias(self):
  self.credential('direct',targets=['dc.example.test']);self.assertEqual(self.capture(self.m.resolve_credential,'ad','ssh','ssh-login')['specificity'],3)
 def test_ambiguity_not_guessed(self):
  self.credential('one',targets=['host:ad']);self.credential('two',targets=['host:ad'])
  with self.assertRaisesRegex(SystemExit,'multiple equally'):self.m.resolve_credential('ad','ssh','ssh-login')
 def test_scope_mismatch(self):
  self.credential('one')
  with self.assertRaisesRegex(SystemExit,'no eligible'):self.m.resolve_credential('ad','acme','ssh-login')
 def test_invalid_inventory_fails_closed(self):
  self.m.INVENTORY.write_text('null');self.credential('one')
  with self.assertRaises(SystemExit):self.m.resolve_credential('ad','ssh','ssh-login')
 def test_ssh_username_comes_from_credential(self):
  self.credential('one',username='service');self.unlock()
  with patch.object(self.m,'decrypt_to_file',side_effect=lambda n,p:p.write_text('test key')):result=self.capture(self.m.materialize_ssh,'one','ad','ssh')
  self.assertEqual(result['username'],'service');self.assertEqual(result['authentication'],'publickey');self.m.cleanup_materialized(result['materialized'])
 def test_missing_credential_username_rejected(self):
  self.credential('one',username='');self.unlock()
  with patch.object(self.m,'decrypt_to_file') as decrypt,self.assertRaises(SystemExit):self.m.materialize_ssh('one','ad','ssh')
  decrypt.assert_not_called()
 def test_ad_login_from_encrypted_payload_not_metadata(self):
  self.credential('one',ctype='active-directory',username='stale');self.unlock()
  secret=json.dumps({'domain':'example.test','username':'service','password':'fixture-only'})
  with patch.object(self.m,'decrypt_to_file',side_effect=lambda n,p:p.write_text(secret)):result=self.capture(self.m.materialize_ssh,'one','ad','ssh')
  self.assertEqual(result['username'],'service@example.test');self.assertEqual(result['authentication'],'password');self.assertNotIn('fixture-only',json.dumps(result));self.assertFalse((Path(result['materialized'])/'credential.json').exists());self.m.cleanup_materialized(result['materialized'])
 def test_password_login_resolves_for_rdp_scope(self):
  self.credential('one',ctype='active-directory',targets=['host:ad'],username='stale');self.m.write_meta('one',{**self.m.read_meta('one'),'scopes':['rdp']})
  self.assertEqual(self.capture(self.m.resolve_credential,'ad','rdp','password-login')['name'],'one')
 def test_materialize_login_returns_file_not_secret(self):
  self.credential('one',ctype='active-directory',targets=['host:ad']);self.m.write_meta('one',{**self.m.read_meta('one'),'scopes':['rdp']});self.unlock('one','rdp')
  secret=json.dumps({'domain':'example.test','username':'service','password':'fixture-only'})
  with patch.object(self.m,'decrypt_to_file',side_effect=lambda n,p:p.write_text(secret)):result=self.capture(self.m.materialize_login,'one','ad','rdp')
  self.assertEqual(result['username'],'service@example.test');self.assertEqual(Path(result['password_file']).read_text(),'fixture-only');self.assertNotIn('fixture-only',json.dumps(result));self.m.cleanup_materialized(result['materialized'])
 def test_locked_stays_locked(self):
  self.credential('one')
  with patch.object(self.m,'decrypt_to_file') as decrypt,self.assertRaisesRegex(SystemExit,'locked'):self.m.materialize_ssh('one','ad','ssh')
  decrypt.assert_not_called()
 def test_decrypt_failure_removes_material(self):
  self.credential('one');self.unlock()
  with patch.object(self.m,'decrypt_to_file',side_effect=SystemExit('failure')),self.assertRaises(SystemExit):self.m.materialize_ssh('one','ad','ssh')
  self.assertEqual(list(self.m.MATERIALIZED.iterdir()),[])
 def test_valid_login_forms(self):
  for name in ('root','service@example.test','EXAMPLE\\service','host$'):self.assertEqual(login_name(name),name)
 def test_invalid_login_no_shell_options(self):
  for name in ('','-root','a b','x;command','$(command)','x\nroot'):
   with self.subTest(name=name),self.assertRaises(ValueError):login_name(name)
 def test_password_login(self):self.assertEqual(password_identity('{"username":"operator","password":"fixture"}','password')['username'],'operator')
 def test_ad_preserves_upn(self):self.assertEqual(password_identity('{"username":"operator@other.test","password":"fixture","domain":"example.test"}','active-directory')['username'],'operator@other.test')
 def test_update_ssh_username(self):
  self.credential('one');self.m.set_login('one','new-user');self.assertEqual(self.m.read_meta('one')['username'],'new-user')
 def test_existing_credentials_default_to_local_managed(self):
  self.credential('one');m=self.m.read_meta('one');self.assertEqual(m['provider'],'local');self.assertEqual(m['storage_class'],'managed');self.assertTrue(m['exportable'])
 def test_pin_local_is_bootstrap_and_non_exportable(self):
  self.credential('one');self.m.pin_local('one');m=self.m.read_meta('one');self.assertEqual(m['provider'],'local');self.assertEqual(m['storage_class'],'bootstrap');self.assertFalse(m['exportable'])

 def test_bootstrap_credential_is_available_without_operator_lease(self):
  self.credential('machine');self.m.pin_local('machine')
  self.assertEqual(self.m.authorization('machine','ssh')[0],'bootstrap')
 def test_managed_credentials_have_individual_leases(self):
  self.credential('one');self.credential('two')
  self.unlock('one','ssh')
  self.assertEqual(self.m.authorization('one','ssh')[0],'credential-lease')
  self.assertIsNone(self.m.authorization('two','ssh')[0])

 def test_authorize_without_scope_uses_credential_policy(self):
  self.credential('one');result=self.capture(self.m.authorize_credential,['one','120'])
  self.assertEqual(result['scopes'],['ssh'])
  self.assertEqual(self.m.authorization('one','ssh')[0],'credential-lease')
 def test_authorize_explicit_invalid_scope_still_fails_closed(self):
  self.credential('one')
  with self.assertRaisesRegex(SystemExit,'exceeds credential policy'):self.m.authorize_credential(['one','120','rdp'])
