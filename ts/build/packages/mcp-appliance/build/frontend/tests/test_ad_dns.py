import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'usr/bin'))
import mcp_acme as acme
import mcp_ad_dns as ad

TOKEN = 'A' * 43

class ADDNSTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = acme.normalize({'dns_provider':'active-directory', 'ad_server':'dc01.example.test',
            'ad_zone':'example.test', 'ad_realm':'example.test', 'primary_domain':'mcp.example.test',
            'credential':'acme-ad', 'alternative_names':['*.apps.example.test']})
        self.provider = ad.ADDNS(self.cfg, {})
    def tearDown(self): self.tmp.cleanup()
    def result(self, text='', code=0): return subprocess.CompletedProcess([], code, text, '')
    def test_defaults_and_custom_migration(self):
        self.assertEqual(acme.normalize({})['dns_provider'], 'active-directory')
        self.assertEqual(acme.normalize({'dns_hook':'site-dns'})['dns_provider'], 'custom')
    def test_normalize_realm(self): self.assertEqual(self.cfg['ad_realm'], 'EXAMPLE.TEST')
    def test_reject_invalid_settings(self):
        for body in [{'ad_server':'192.0.2.1'}, {'ad_zone':'example.test\nupdate'}, {'ad_realm':'A;B'},
                     {'ad_ttl':True}, {'ad_propagation_timeout':999}, {'dns_provider':'bad'}]:
            with self.subTest(body=body), self.assertRaises(ValueError): acme.normalize(body)
    def test_wildcard_owner(self): self.assertEqual(ad.owner_for(self.cfg,'*.apps.example.test'), '_acme-challenge.apps.example.test.')
    def test_order_scope(self):
        with self.assertRaises(ValueError): ad.owner_for(self.cfg,'unrequested.example.test')
    def test_zone_boundary(self):
        cfg = {**self.cfg, 'primary_domain':'evilexample.test'}
        with self.assertRaises(ValueError): ad.owner_for(cfg, cfg['primary_domain'])
    def test_secure_specific_update(self):
        with patch.object(ad,'tool',side_effect=lambda n:n),patch.object(ad,'invoke',return_value=self.result()) as run:
            self.provider.update('_acme-challenge.mcp.example.test.', TOKEN, delete=True)
        self.assertIn('-g',run.call_args.args[0]); self.assertIn('-v',run.call_args.args[0])
        text=run.call_args.kwargs['input'];self.assertIn('TXT "'+TOKEN+'"',text)
        self.assertNotIn('update delete _acme-challenge.mcp.example.test.\nsend',text)
    def test_no_unsigned_fallback(self):
        with patch.object(ad,'tool',side_effect=lambda n:n),patch.object(ad,'invoke',return_value=self.result(code=1)) as run,self.assertRaisesRegex(ValueError,'No unsigned'):
            self.provider.update('_acme-challenge.mcp.example.test.',TOKEN)
        self.assertEqual(run.call_count,1)
    def test_invalid_token(self):
        with self.assertRaises(ValueError): self.provider.hook('deploy_challenge','mcp.example.test','bad"\n',self.root)
    def test_preexisting_value_not_removed(self):
        with patch.object(self.provider,'check_zone'),patch.object(self.provider,'values',return_value={TOKEN}),patch.object(self.provider,'update') as update:
            self.provider.hook('deploy_challenge','mcp.example.test',TOKEN,self.root)
            self.provider.hook('clean_challenge','mcp.example.test',TOKEN,self.root)
        update.assert_not_called();self.assertEqual(list(self.root.iterdir()),[])
    def test_deploy_and_value_only_cleanup(self):
        with patch.object(self.provider,'check_zone'),patch.object(self.provider,'values',side_effect=[{'other'}, {'other',TOKEN}]),patch.object(self.provider,'update') as update:
            self.provider.hook('deploy_challenge','mcp.example.test',TOKEN,self.root)
            self.assertEqual(len(list(self.root.glob('ad-dns-*.json'))),1)
            self.provider.cleanup(self.root)
        self.assertEqual(update.call_count,2)
        self.assertEqual(update.call_args.kwargs,{'delete':True});self.assertEqual(list(self.root.iterdir()),[])
    def test_deploy_failure_cleanup(self):
        with patch.object(self.provider,'check_zone'),patch.object(self.provider,'values',return_value=set()),patch.object(self.provider,'update',side_effect=[ValueError('failed'),None]) as update,self.assertRaises(ValueError):
            self.provider.hook('deploy_challenge','mcp.example.test',TOKEN,self.root)
        self.assertEqual(update.call_count,2);self.assertEqual(list(self.root.iterdir()),[])
    def test_no_broad_cleanup_without_marker(self):
        with patch.object(self.provider,'update') as update:self.provider.cleanup(self.root)
        update.assert_not_called()
    def test_parse_authoritative_txt(self):
        text=';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n;; flags: qr aa;\n_acme-challenge.mcp.example.test. 60 IN TXT "'+TOKEN+'"\n'
        with patch.object(ad,'tool',side_effect=lambda n:n),patch.object(ad,'invoke',return_value=self.result(text)):
            self.assertEqual(self.provider.values('_acme-challenge.mcp.example.test.'),{TOKEN})
    def test_non_authoritative_refused(self):
        with patch.object(ad,'tool',side_effect=lambda n:n),patch.object(ad,'invoke',return_value=self.result('status: NOERROR,\nflags: qr ra;')),self.assertRaisesRegex(ValueError,'authoritative'):
            self.provider.values('_acme-challenge.mcp.example.test.')
    def test_alias_refused(self):
        with patch.object(self.provider,'query',return_value=[('CNAME','other.example.test.')]),self.assertRaisesRegex(ValueError,'alias'):
            self.provider.values('_acme-challenge.mcp.example.test.')
    def test_zone_primary_must_match(self):
        with patch.object(self.provider,'query',return_value=[('SOA','other.example.test. admin.example.test. 1 2 3 4 5')]),self.assertRaisesRegex(ValueError,'primary'):
            self.provider.check_zone()
    def test_principal_forms(self):
        for name in ['svc-acme','EXAMPLE\\svc-acme','svc-acme@EXAMPLE.TEST']:
            credential={'domain':'example.test','username':name,'password':'test-fixture-not-a-password'}
            self.assertEqual(ad.principal_password(credential,'EXAMPLE.TEST')[0],'svc-acme@EXAMPLE.TEST')
    def test_principal_injection_and_wrong_realm(self):
        for name in ['-admin','svc;id','svc@OTHER.TEST']:
            with self.assertRaises(ValueError):ad.principal_password({'domain':'example.test','username':name,'password':'fixture'},'EXAMPLE.TEST')
    def test_password_never_argv_or_environment_and_cache_removed(self):
        secret='fixture-only-never-a-real-password'
        credential={'domain':'example.test','username':'svc-acme','password':secret}
        with patch.object(ad,'missing_tools',return_value=[]),patch.object(ad,'tool',side_effect=lambda n:n),patch.object(ad,'invoke',return_value=self.result()) as run:
            with ad.kerberos(self.cfg,credential,root=self.root/'runtime') as env:
                self.assertTrue(Path(env['KRB5_CONFIG']).exists());self.assertTrue(env['KRB5CCNAME'].startswith('FILE:'))
            calls=run.call_args_list
            self.assertEqual(calls[0].kwargs['input'],secret+'\n')
            for call in calls:self.assertNotIn(secret,repr(call.args))
        self.assertEqual(list((self.root/'runtime').iterdir()),[])
    def test_failed_auth_cleans_runtime(self):
        credential={'domain':'example.test','username':'svc-acme','password':'fixture-only'}
        with patch.object(ad,'missing_tools',return_value=[]),patch.object(ad,'tool',side_effect=lambda n:n),patch.object(ad,'invoke',return_value=self.result(code=1)) as run,self.assertRaisesRegex(ValueError,'authentication failed'):
            with ad.kerberos(self.cfg,credential,root=self.root/'runtime'):pass
        self.assertEqual(run.call_count,1);self.assertEqual(list((self.root/'runtime').iterdir()),[])

class ADIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.cfg=acme.normalize({'enabled':True,'email':'admin@example.test','primary_domain':'mcp.example.test',
            'accept_terms':True,'dns_provider':'active-directory','ad_server':'dc01.example.test',
            'ad_zone':'example.test','ad_realm':'example.test','credential':'acme-ad'})
        self.cred={'name':'acme-ad','type':'active-directory','scopes':['acme'],'allowed_hosts':['dc01.example.test']}
        self.vault={'credentials':[self.cred],'lease':{'expires':4102444800,'scopes':['acme']},'grants':[]}
        self.manager=acme.Certificates({'vault_status':lambda:self.vault},base=self.base,native=self.base/'native.conf')
        acme.atomic(self.base/'config/hosts.json', json.dumps({'hosts':{'dc':{'platform':'windows','hostname':'dc01.example.test','address':'192.0.2.10'}},'groups':{}}))
    def tearDown(self):self.tmp.cleanup()
    def readiness(self):
        with patch.object(acme.os.path,'ismount',return_value=True),patch.object(acme.shutil,'which',return_value='/usr/bin/tool'),patch.object(ad,'missing_tools',return_value=[]):
            return self.manager.readiness(self.cfg)
    def test_ready_with_ad_credential_no_custom_hook(self):self.assertTrue(self.readiness()['ready'])
    def test_wrong_credential_type_rejected(self):
        self.cred['type']='api-token';self.assertFalse(self.readiness()['ready'])
    def test_missing_explicit_scope_rejected(self):
        self.cred['scopes']=[];self.assertFalse(self.readiness()['ready'])
    def test_other_ad_server_rejected(self):
        self.cred['allowed_hosts']=['other.example.test'];self.assertFalse(self.readiness()['ready'])
    def test_locked_vault_requires_grant(self):
        self.vault['lease']=None;self.assertFalse(self.readiness()['ready'])
        self.vault['grants']=[{'scope':'acme','credential':'acme-ad','expires':4102444800}]
        self.assertTrue(self.readiness()['ready'])
    def test_runtime_absent_blocks_provider(self):
        with patch.object(ad,'missing_tools',return_value=['nsupdate']):
            self.assertTrue(any('nsupdate' in text for text in ad.prerequisites(self.cfg)))
    def test_exception_removes_temporary_kerberos_cache(self):
        credential={'domain':'example.test','username':'svc-acme','password':'fixture-not-a-real-password'}
        with patch.object(ad,'missing_tools',return_value=[]),patch.object(ad,'tool',side_effect=lambda n:n),patch.object(ad,'invoke',return_value=subprocess.CompletedProcess([],0,'','')):
            with self.assertRaisesRegex(ValueError,'fixture failure'):
                with ad.kerberos(self.cfg,credential,root=self.base/'runtime') as env:
                    Path(env['KRB5CCNAME'][5:]).write_text('fixture ticket')
                    raise ValueError('fixture failure')
        self.assertEqual(list((self.base/'runtime').iterdir()),[])
