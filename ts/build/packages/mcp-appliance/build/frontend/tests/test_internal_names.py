import json, os, socket, ssl, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_acme as acme
import mcp_ad_dns as ad
import mcp_tlsalpn as alpn
import mcp_certificate_names as names
import test_tlsalpn as fixtures

def config(**kw):
 return acme.normalize({'directory_url':'https://ca.example.test/directory','internal_ca':True,'primary_domain':'mcp','alternative_names':['mcp.example.test'],'challenge':'http-01','http_ready':True,**kw})

class NamePolicyTests(unittest.TestCase):
 def test_internal_primary_and_san(self):
  c=config(alternative_names=['MCP','alias','mcp.example.test']);self.assertEqual(c['primary_domain'],'mcp');self.assertEqual(c['alternative_names'],['alias','mcp.example.test'])
 def test_public_short_rejected(self):
  for c in ({'primary_domain':'mcp'},{'alternative_names':['mcp']},{'directory_url':'https://ca.example.test/directory','primary_domain':'mcp'}):
   with self.subTest(c=c),self.assertRaises(ValueError):acme.normalize(c)
 def test_public_internal_override_rejected(self):
  for url in (acme.LE,acme.STAGING,'https://ACME.letsencrypt.org./directory'):
   with self.subTest(url=url),self.assertRaises(ValueError):config(directory_url=url)
 def test_internal_flag_is_boolean(self):
  with self.assertRaises(ValueError):config(internal_ca='true')
 def test_no_short_wildcards(self):
  with self.assertRaises(ValueError):config(alternative_names=['*.mcp'])
 def test_bad_labels_rejected(self):
  for n in ('-mcp','mcp-','m_cp','123','localhost','foo.localhost','x'*64,'a/b','a:443'):
   with self.subTest(n=n),self.assertRaises(ValueError):config(primary_domain=n)
 def test_public_fqdn_unchanged(self):self.assertEqual(acme.normalize({'primary_domain':'MCP.Example.Test'})['primary_domain'],'mcp.example.test')
 def test_short_url_without_path(self):self.assertEqual(config(primary_domain='https://MCP/')['primary_domain'],'mcp')
 def test_internal_challenge_policy(self):
  for c in ('http-01','tls-alpn-01'):self.assertEqual(config(challenge=c)['primary_domain'],'mcp')
  with self.assertRaisesRegex(ValueError,'fully qualified'):config(challenge='dns-01',dns_provider='active-directory')
 def test_inventory_and_realm_stay_qualified(self):
  with self.assertRaises(ValueError):acme.normalize({'directory_url':'https://ca.example.test/directory','internal_ca':True,'primary_domain':'mcp.example.test','challenge':'dns-01','dns_provider':'active-directory','ad_server':'dc'})
 def test_save_preserves_short_literal(self):
  with tempfile.TemporaryDirectory() as td:
   m=acme.Certificates(base=td,native=Path(td)/'native.conf')
   with patch.object(acme.os.path,'ismount',return_value=True),patch.object(m,'status',return_value={}):r=m.save(config(challenge='http-01'))
   self.assertEqual(r['config']['primary_domain'],'mcp');self.assertEqual(m.config()['primary_domain'],'mcp')

class IdentityTests(unittest.TestCase):
 def test_hostname_plus_search(self):self.assertEqual(names.appliance_identity('mcp','search example.test')['fqdn'],'mcp.example.test')
 def test_already_qualified(self):self.assertEqual(names.appliance_identity('MCP.Example.Test.','search other.test')['fqdn'],'mcp.example.test')
 def test_domain_directive(self):self.assertEqual(names.appliance_identity('mcp','domain example.test')['fqdn'],'mcp.example.test')
 def test_duplicates_not_ambiguous(self):self.assertEqual(names.appliance_identity('mcp','search example.test example.test')['fqdn'],'mcp.example.test')
 def test_multiple_domains_not_guessed(self):self.assertEqual(names.appliance_identity('mcp','search example.test other.test')['fqdn'],'')
 def test_comments(self):self.assertEqual(names.appliance_identity('mcp','search example.test # comment')['fqdn'],'mcp.example.test')
 def test_missing_suffix_not_invented(self):self.assertEqual(names.appliance_identity('mcp','nameserver 127.0.0.53')['fqdn'],'')
 def test_invalid_hostname(self):
  for n in ('localhost','127.0.0.1','mcp;id','bad_name','-mcp'):self.assertEqual(names.appliance_identity(n,'search example.test')['fqdn'],'')
 def test_route_only_not_search(self):self.assertEqual(names.appliance_identity('mcp','search ~example.test')['fqdn'],'')

class ShortChallengeTests(unittest.TestCase):
 def test_ad_relative_owner(self):
  c=config();c['ad_zone']='example.test';self.assertEqual(ad.owner_for(c,'mcp'),'_acme-challenge.mcp.example.test.')
 def test_ad_requires_internal_policy(self):
  c=config();c['ad_zone']='example.test';c['internal_ca']=False
  with self.assertRaises(ValueError):ad.owner_for(c,'mcp')
 def test_ad_requires_zone(self):
  with self.assertRaises(ValueError):ad.owner_for(config(),'mcp')
 def test_ad_unrequested_refused(self):
  c=config();c['ad_zone']='example.test'
  with self.assertRaises(ValueError):ad.owner_for(c,'other')
 def test_short_and_long_dns_owners_match(self):
  c=config();c['ad_zone']='example.test';self.assertEqual(ad.owner_for(c,'mcp'),ad.owner_for(c,'mcp.example.test'))
 def test_tls_short_handshakes(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'tls-challenges').mkdir();fixtures.generate(root,'mcp')
   cfg=config(challenge='tls-alpn-01');alpn.publish(root,cfg,'deploy_challenge','mcp',fixtures.TOKEN,fixtures.DIGEST)
   server=alpn.Server(('127.0.0.1',0),socket.AF_INET,root/'tls-challenges',['mcp'])
   thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
   try:
    for version in (ssl.TLSVersion.TLSv1_2,ssl.TLSVersion.TLSv1_3):
     with socket.create_connection(server.server_address,2) as sock:
      with fixtures.client_context(version=version).wrap_socket(sock,server_hostname='mcp') as tls:
       self.assertEqual(tls.selected_alpn_protocol(),'acme-tls/1')
       alpn.verify_certificate(ssl.DER_cert_to_PEM_cert(tls.getpeercert(True)),'mcp',bytes.fromhex(fixtures.DIGEST))
    with self.assertRaises(OSError):
     with socket.create_connection(server.server_address,2) as sock:fixtures.client_context().wrap_socket(sock,server_hostname='other')
   finally:
    server.shutdown();server.close_connections();server.server_close();thread.join()
    alpn.publish(root,cfg,'clean_challenge','mcp',fixtures.TOKEN,fixtures.DIGEST)
   self.assertEqual(list((root/'tls-challenges').iterdir()),[])
 def test_tls_publisher_requires_internal_policy(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'tls-challenges').mkdir();fixtures.generate(root,'mcp');cfg=config();cfg['internal_ca']=False
   with self.assertRaises(ValueError):alpn.publish(root,cfg,'deploy_challenge','mcp',fixtures.TOKEN,fixtures.DIGEST)
 def test_certificate_exact_short_san_validation(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);m=acme.Certificates(base=root,native=root/'native.conf');cfg=config(challenge='http-01',alternative_names=[])
   acme.atomic(m.settings,json.dumps(cfg));stage=root/'state/acme-stage-test';stage.mkdir(parents=True)
   cert,key=fixtures.generate(root,'mcp')
   with patch.dict(os.environ,MCP_ACME_STAGE=str(stage)):m.hook(['deploy_cert','mcp',str(key),str(cert),str(cert)])
   self.assertTrue((stage/'web.crt').exists())
   acme.atomic(m.settings,json.dumps(config(challenge='http-01',alternative_names=['mcp.example.test'])))
   with patch.dict(os.environ,MCP_ACME_STAGE=str(stage)),self.assertRaisesRegex(ValueError,'DNS names'):m.hook(['deploy_cert','mcp',str(key),str(cert),str(cert)])
