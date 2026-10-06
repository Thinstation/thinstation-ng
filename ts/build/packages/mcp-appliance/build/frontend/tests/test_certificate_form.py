import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_acme as acme
import mcp_certificate_form as form

class CertificateFormTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
  self.inventory={'hosts':{'ad':{'platform':'windows','address':'192.0.2.10','hostname':'dc.example.test'},'linux':{'platform':'linux','hostname':'linux.example.test'},'missing-name':{'platform':'windows','address':'192.0.2.11'}},'groups':{'windows':{'hosts':['ad']}}}
  acme.atomic(self.base/'config/hosts.json',json.dumps(self.inventory))
  self.manager=acme.Certificates(base=self.base,native=self.base/'native.conf')
  self.cfg=acme.normalize({'ad_host':'ad','ad_zone':'example.test','ad_realm':'EXAMPLE.TEST','credential':'test-ad'})
 def tearDown(self):self.tmp.cleanup()
 def test_ca_prefix_assumed(self):self.assertEqual(form.directory('ca.example.test/directory'),'https://ca.example.test/directory')
 def test_ca_always_https(self):
  for challenge in ('dns-01','http-01'):
   self.assertEqual(acme.normalize({'challenge':challenge,'directory_url':'ca.example.test/directory'})['directory_url'],'https://ca.example.test/directory')
 def test_existing_https_retained(self):self.assertEqual(form.directory('https://ca.example.test/directory'),'https://ca.example.test/directory')
 def test_plain_http_ca_rejected(self):
  with self.assertRaises(ValueError):form.directory('http://ca.example.test/directory')
 def test_unsafe_ca_rejected(self):
  for value in ('https://u:p@ca.example.test/','https://ca.example.test/?a=b','https://ca.example.test/#f','https://ca.example.test:bad/','ca.example.test /path'):
   with self.subTest(value=value),self.assertRaises(ValueError):form.directory(value)
 def test_hostname_prefix_removed(self):
  for value in ('mcp.example.test','https://mcp.example.test/','http://mcp.example.test'):
   self.assertEqual(acme.normalize({'primary_domain':value})['primary_domain'],'mcp.example.test')
 def test_service_url_not_host(self):
  for value in ('https://mcp.example.test:8443/','https://mcp.example.test/path','https://u:p@mcp.example.test/'):
   with self.assertRaises(ValueError):acme.domain(value)
 def test_options_are_windows_fqdn_only(self):self.assertEqual([h['alias'] for h in self.manager.inventory_candidates()],['ad'])
 def test_group_metadata_available(self):self.assertEqual(self.manager.inventory_candidates()[0]['groups'],['windows'])
 def test_selected_alias_resolves(self):self.assertEqual(self.manager.bind_inventory(self.cfg,True)['ad_server'],'dc.example.test')
 def test_posted_server_cannot_override_inventory(self):self.assertEqual(self.manager.bind_inventory({**self.cfg,'ad_server':'other.example.test'},True)['ad_server'],'dc.example.test')
 def test_unlisted_server_rejected(self):
  with self.assertRaisesRegex(ValueError,'Inventory'):self.manager.bind_inventory({**self.cfg,'ad_host':'','ad_server':'unlisted.example.test'},True)
 def test_old_server_migrates_to_alias(self):self.assertEqual(self.manager.bind_inventory({**self.cfg,'ad_host':'','ad_server':'dc.example.test'},True)['ad_host'],'ad')
 def test_linux_alias_rejected(self):
  with self.assertRaises(ValueError):self.manager.bind_inventory({**self.cfg,'ad_host':'linux'},True)
 def test_removed_host_blocks_execution(self):
  acme.atomic(self.base/'config/hosts.json',json.dumps({'hosts':{},'groups':{}}))
  self.assertEqual(self.manager.bind_inventory(self.cfg)['ad_server'],'')
  with self.assertRaises(ValueError):self.manager.bind_inventory(self.cfg,True)
 def test_http_discards_dns_fields(self):
  cfg=acme.normalize({'challenge':'http-01','ad_host':'unknown','ad_server':'not a name','ad_zone':[],'credential':'unknown','dns_provider':'invalid'})
  self.assertEqual(cfg['ad_host'],'');self.assertEqual(cfg['credential'],'')
 def test_dns_discards_http_fields(self):
  cfg=acme.normalize({'challenge':'dns-01','http_mode':'invalid','http_source_networks':'bad','http_ready':'bad'})
  self.assertEqual(cfg['http_source_networks'],[]);self.assertFalse(cfg['http_ready'])
 def test_external_http_discards_source_filter(self):
  cfg=acme.normalize({'challenge':'http-01','http_mode':'external','http_source_networks':['bad'],'http_public_access':True})
  self.assertEqual(cfg['http_source_networks'],[]);self.assertFalse(cfg['http_public_access'])
 def test_alpn_managed_method_available(self):
  self.assertTrue(next(x for x in form.CHALLENGES if x['value']=='tls-alpn-01')['enabled'])
  self.assertEqual(acme.normalize({'challenge':'tls-alpn-01'})['challenge'],'tls-alpn-01')
 def test_no_restart_or_issuance_on_save(self):
  with patch.object(acme.os.path,'ismount',return_value=True),patch.object(self.manager,'status',return_value={}),patch.object(acme.subprocess,'run') as run:self.manager.save(self.cfg)
  run.assert_not_called()
