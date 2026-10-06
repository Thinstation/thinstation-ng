import json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
from mcp_acme_authorization import ACMEAuthorization, scheduled_worker_authorized

class ACMEAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        cred=self.base/'vault/credentials/ACME.cred';cred.parent.mkdir(parents=True);cred.write_bytes(b'encrypted-placeholder');cred.chmod(0o600)
        meta=self.base/'vault/metadata/ACME.json';meta.parent.mkdir(parents=True)
        meta.write_text(json.dumps({'name':'ACME','type':'active-directory','scopes':['acme'],'allowed_hosts':['group:windows']}));meta.chmod(0o600)
        self.cfg={'enabled':True,'automatic':True,'directory_url':'https://ca.example.test/directory','internal_ca':True,'email':'admin@example.test','primary_domain':'mcp.example.test','alternative_names':['mcp'],'challenge':'dns-01','dns_hook':'','credential':'ACME','key_algorithm':'rsa','renew_days':30,'accept_terms':True,'http_ready':False,'test_only':False,'dns_provider':'active-directory','ad_host':'ad','ad_server':'dc.example.test','ad_zone':'example.test','ad_realm':'EXAMPLE.TEST','ad_ttl':60,'ad_propagation_timeout':60,'http_mode':'standalone','http_source_networks':[],'http_public_access':False,'alpn_ready':False,'alpn_source_networks':[],'alpn_public_access':False}
        self.inventory={'hosts':{'ad':{'platform':'windows','hostname':'dc.example.test','address':'192.0.2.10'}},'groups':{'windows':{'hosts':['ad']}}}
        self.policy=ACMEAuthorization(self.base)
    def tearDown(self):self.tmp.cleanup()
    def test_explicit_authorization_is_required_and_persistent(self):
        before=self.policy.status(self.cfg,self.inventory);self.assertFalse(before['automatic_authorized']);self.assertTrue(before['can_authorize_automatic'])
        self.policy.authorize(self.cfg,self.inventory,before['revision'],'admin')
        self.assertTrue(ACMEAuthorization(self.base).status(self.cfg,self.inventory)['automatic_authorized'])
    def test_configuration_change_invalidates(self):
        s=self.policy.status(self.cfg,self.inventory);self.policy.authorize(self.cfg,self.inventory,s['revision'],'admin')
        changed={**self.cfg,'primary_domain':'other.example.test'}
        self.assertFalse(self.policy.status(changed,self.inventory)['automatic_authorized'])
    def test_credential_scope_change_invalidates(self):
        s=self.policy.status(self.cfg,self.inventory);self.policy.authorize(self.cfg,self.inventory,s['revision'],'admin')
        p=self.base/'vault/metadata/ACME.json';d=json.loads(p.read_text());d['scopes']=['ssh'];p.write_text(json.dumps(d));p.chmod(0o600)
        self.assertFalse(self.policy.status(self.cfg,self.inventory)['automatic_authorized'])
    def test_revoke_is_persistent(self):
        s=self.policy.status(self.cfg,self.inventory);self.policy.authorize(self.cfg,self.inventory,s['revision'],'admin');self.policy.revoke('admin')
        self.assertFalse(ACMEAuthorization(self.base).status(self.cfg,self.inventory)['automatic_authorized'])
    def test_stale_revision_rejected(self):
        with self.assertRaises(ValueError):self.policy.authorize(self.cfg,self.inventory,'0'*64,'admin')
    def test_non_acme_and_non_scheduled_commands_rejected(self):
        self.assertFalse(scheduled_worker_authorized('ssh','ACME','ACME_CREDENTIAL_FILE',[] ,base=self.base))
        self.assertFalse(scheduled_worker_authorized('acme','ACME','ACME_CREDENTIAL_FILE',['/bin/sh'],base=self.base))
    def test_policy_contains_no_secret(self):
        s=self.policy.status(self.cfg,self.inventory);self.policy.authorize(self.cfg,self.inventory,s['revision'],'admin')
        data=self.policy.path.read_bytes();self.assertNotIn(b'encrypted-placeholder',data);self.assertEqual(self.policy.path.stat().st_mode&0o777,0o600)

if __name__=='__main__':unittest.main()
