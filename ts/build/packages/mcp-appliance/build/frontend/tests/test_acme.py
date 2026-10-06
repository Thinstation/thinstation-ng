import json, os, ssl, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_acme as acme
class AcmeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)/'appliance';self.base.mkdir()
  self.m=acme.Certificates(base=self.base,native=self.base/'native.conf')
  self.cfg=acme.normalize(dict(enabled=True,email='admin@example.test',primary_domain='mcp.example.test',challenge='http-01',http_ready=True,accept_terms=True))
  acme.atomic(self.m.settings,json.dumps(self.cfg));(self.base/'state').mkdir()
 def tearDown(self):self.tmp.cleanup()
 def pair(self,names,stem='new'):
  key,cert=self.base/(stem+'.key'),self.base/(stem+'.crt')
  args=['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:prime256v1','-nodes','-days','2','-subj','/CN=mcp.example.test','-keyout',str(key),'-out',str(cert)]
  if names:args+=['-addext','subjectAltName='+','.join('DNS:'+n for n in names)]
  subprocess.run(args,check=True,capture_output=True);return key,cert
 def stage(self,names,cfg=None):
  key,cert=self.pair(names);stage=self.base/'state/acme-stage-test';stage.mkdir()
  if cfg:acme.atomic(self.m.settings,json.dumps(cfg))
  with patch.dict(os.environ,MCP_ACME_STAGE=str(stage)):self.m.hook(['deploy_cert',self.cfg['primary_domain'],str(key),str(cert),str(cert)])
  return stage
 def test_matching_san(self):self.assertTrue((self.stage(['mcp.example.test'])/'web.crt').exists())
 def test_wrong_san_correct_cn(self):
  with self.assertRaisesRegex(ValueError,'DNS names'):self.stage(['wrong.example.test'])
 def test_missing_san(self):
  with self.assertRaisesRegex(ValueError,'DNS names'):self.stage([])
 def test_extra_san(self):
  with self.assertRaisesRegex(ValueError,'DNS names'):self.stage(['mcp.example.test','unexpected.example.test'])
 def test_missing_requested_san(self):
  with self.assertRaisesRegex(ValueError,'DNS names'):self.stage(['mcp.example.test'],{**self.cfg,'alternative_names':['alias.example.test']})
 def test_exact_wildcard(self):
  names=['mcp.example.test','*.apps.example.test']
  self.assertTrue((self.stage(names,{**self.cfg,'challenge':'dns-01','alternative_names':[names[1]]})/'web.crt').exists())
 def test_expired(self):
  with patch('mcp_acme.time.time',return_value=4102444800),self.assertRaisesRegex(ValueError,'currently valid'):self.stage(['mcp.example.test'])
 def test_staging_not_live(self):self.assertTrue(acme.normalize({'directory_url':acme.STAGING,'test_only':False})['test_only'])
 def test_unsafe_input(self):
  for body in [{'primary_domain':'127.0.0.1'},{'primary_domain':'localhost'},{'primary_domain':'bad;command.example.test'},{'directory_url':'http://ca.example.test/directory'},{'directory_url':'https://user:password@ca.example.test/'},{'enabled':'false'},{'renew_days':True},{'secret':'not-accepted'}]:
   with self.subTest(body=body),self.assertRaises(ValueError):acme.normalize(body)
 def test_http_no_wildcards(self):
  with self.assertRaises(ValueError):acme.normalize({'challenge':'http-01','alternative_names':['*.example.test']})
 def test_ad_dns_rejects_short_certificate_names(self):
  base={'directory_url':'https://ca.example.test/directory','internal_ca':True,'challenge':'dns-01','dns_provider':'active-directory'}
  for body in ({**base,'primary_domain':'mcp'},{**base,'primary_domain':'mcp.example.test','alternative_names':['mcp']}):
   with self.subTest(body=body),self.assertRaisesRegex(ValueError,'fully qualified'):acme.normalize(body)
 def test_internal_short_name_still_allowed_for_non_ad_dns_challenge(self):
  cfg=acme.normalize({'directory_url':'https://ca.example.test/directory','internal_ca':True,'challenge':'http-01','primary_domain':'mcp','http_ready':True})
  self.assertEqual(cfg['primary_domain'],'mcp')
 def test_force_confirm(self):
  with self.assertRaisesRegex(ValueError,'Confirm force'):self.m.action({'action':'force'})
 def test_disabled_no_job(self):
  acme.atomic(self.m.settings,json.dumps({**self.cfg,'enabled':False}))
  with patch('mcp_acme.command') as command,self.assertRaisesRegex(ValueError,'Enable ACME'):self.m.action({'action':'issue'})
  command.assert_not_called()
 def test_save_no_issuance(self):
  with patch('mcp_acme.os.path.ismount',return_value=True),patch.object(self.m,'status',return_value={}),patch('mcp_acme.subprocess.run') as run:self.m.save(self.cfg)
  run.assert_not_called();self.assertEqual(self.m.settings.stat().st_mode&0o777,0o600)
 def test_manual_only_no_scheduled_run(self):
  with patch('mcp_acme.subprocess.run') as run:self.assertEqual(self.m.run('scheduled'),0)
  run.assert_not_called()
 def test_wrong_key_rejected(self):
  key,cert=self.pair(['mcp.example.test']);other,_=self.pair(['mcp.example.test'],'other')
  stage=self.base/'state/acme-stage-test';stage.mkdir()
  with patch.dict(os.environ,MCP_ACME_STAGE=str(stage)),self.assertRaises(ssl.SSLError):self.m.hook(['deploy_cert','mcp.example.test',str(other),str(cert),str(cert)])
  self.assertFalse((stage/'web.key').exists())
 def test_failed_web_reload_restores_pair(self):
  identity=self.base/'identity';identity.mkdir();stage=self.base/'state/acme-stage-test';stage.mkdir()
  for name in ('web.key','web.crt'):acme.atomic(identity/name,'old '+name);acme.atomic(stage/name,'new '+name)
  with patch('mcp_acme.command',return_value=subprocess.CompletedProcess([],0,'','')),patch.object(self.m,'check_web',side_effect=ValueError('web failed')),self.assertRaisesRegex(ValueError,'web failed'):self.m.install_pair(stage)
  for name in ('web.key','web.crt'):self.assertEqual((identity/name).read_text(),'old '+name)
 def test_missing_dns_hook_blocks_issue(self):
  with patch('mcp_acme.os.path.ismount',return_value=True),patch('mcp_acme.shutil.which',return_value='/usr/bin/dehydrated'):
   report=self.m.readiness({**self.cfg,'challenge':'dns-01','dns_provider':'custom','dns_hook':''})
  self.assertFalse(report['ready']);self.assertTrue(any('DNS challenge hook' in s for s in report['issues']))
 def test_queued_blocks_save(self):
  self.m.job_write('queued','test')
  with patch('mcp_acme.os.path.ismount',return_value=True),self.assertRaisesRegex(ValueError,'finish'):self.m.save(self.cfg)
