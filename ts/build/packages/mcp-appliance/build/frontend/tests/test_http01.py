from http.client import HTTPConnection
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_http01 as http
import mcp_acme as acme
NAME='mcp.example.test'
TOKEN='a'*43
VALUE=TOKEN+'.'+'b'*43

def configuration(**values):
    return acme.normalize(dict(challenge='http-01',http_mode='standalone',primary_domain=NAME,http_ready=True,http_source_networks=['192.0.2.10'],**values))

class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.stage=Path(self.tmp.name);self.root=self.stage/'http-tokens';self.root.mkdir(mode=0o700);self.cfg=configuration()
        self.server=http.Server(('127.0.0.1',0),socket.AF_INET,self.root,[NAME,'alias.example.test'])
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01});self.thread.start()
        http.publish(self.stage,self.cfg,'deploy_challenge',NAME,TOKEN,VALUE)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path=http.PREFIX+TOKEN,method='GET',host=NAME,headers=None):
        conn=HTTPConnection(*self.server.server_address,timeout=3)
        try:
            conn.request(method,path,headers={'Host':host,**(headers or {})});res=conn.getresponse()
            return res.status,res.read(),dict(res.getheaders())
        finally:conn.close()
    def test_exact_token(self):
        code,body,headers=self.request();self.assertEqual((code,body),(200,VALUE.encode()));self.assertEqual(headers['Cache-Control'],'no-store')
    def test_head(self):
        code,body,headers=self.request(method='HEAD');self.assertEqual((code,body),(200,b''));self.assertEqual(headers['Content-Length'],str(len(VALUE)))
    def test_port_host(self):self.assertEqual(self.request(host=NAME.upper()+':80')[0],200)
    def test_wrong_host(self):self.assertEqual(self.request(host='wrong.example.test')[0],404)
    def test_unpublished_alias(self):self.assertEqual(self.request(host='alias.example.test')[0],404)
    def test_unpublished_token(self):self.assertEqual(self.request(path=http.PREFIX+'c'*43)[0],404)
    def test_no_directory_or_api_access(self):
        for path in ('/','/api/status','/etc/passwd',http.PREFIX,http.PREFIX+'../secret',http.PREFIX+TOKEN+'?x=1',http.PREFIX+'%2e%2e/secret'):
            with self.subTest(path=path):self.assertEqual(self.request(path=path)[0],404)
    def test_methods_rejected(self):
        for method in ('POST','PUT','DELETE','CONNECT','TRACE','OPTIONS'):
            with self.subTest(method=method):self.assertEqual(self.request(method=method)[0],405)
    def test_body_or_chunked_rejected(self):
        self.assertEqual(self.request(headers={'Content-Length':'1'})[0],400);self.assertEqual(self.request(headers={'Transfer-Encoding':'chunked'})[0],400)
    def test_cleanup_hides_token(self):
        http.publish(self.stage,self.cfg,'clean_challenge',NAME,TOKEN,VALUE);self.assertEqual(self.request()[0],404)
    def test_expired_token(self):
        p=http.entry(self.root,NAME,TOKEN);row=json.loads(p.read_text());row['expires']=time.time()-1;p.write_text(json.dumps(row));self.assertEqual(self.request()[0],404)
    def test_symlink_denied(self):
        p=http.entry(self.root,NAME,TOKEN);p.unlink();p.symlink_to('/etc/passwd');self.assertEqual(self.request()[0],404)
    def test_unsafe_permissions_denied(self):
        http.entry(self.root,NAME,TOKEN).chmod(0o644);self.assertEqual(self.request()[0],404)
    def test_order_boundary(self):
        with self.assertRaises(ValueError):http.publish(self.stage,self.cfg,'deploy_challenge','other.example.test',TOKEN,VALUE)
    def test_invalid_authorization(self):
        with self.assertRaises(ValueError):http.publish(self.stage,self.cfg,'deploy_challenge',NAME,TOKEN,'wrong')

class PolicyTests(unittest.TestCase):
    def test_default_builtin(self):self.assertEqual(acme.normalize({})['http_mode'],'standalone')
    def test_legacy_external_preserved(self):self.assertEqual(acme.normalize({'challenge':'http-01','http_ready':True})['http_mode'],'external')
    def test_source_normalization(self):self.assertEqual(configuration()['http_source_networks'],['192.0.2.10/32'])
    def test_ipv6_source(self):
        cfg=configuration();cfg['http_source_networks']=['2001:db8::1'];self.assertEqual(acme.normalize(cfg)['http_source_networks'],['2001:db8::1/128'])
    def test_unrestricted_requires_explicit_setting(self):
        cfg=configuration();cfg['http_source_networks']=['0.0.0.0/0']
        with self.assertRaises(ValueError):acme.normalize(cfg)
    def test_invalid_sources(self):
        for value in ('ca.example.test','192.0.2.10; accept','bad',10):
            cfg=configuration();cfg['http_source_networks']=[value]
            with self.subTest(value=value),self.assertRaises(ValueError):acme.normalize(cfg)
    def test_explicit_authorization_required(self):
        cfg=configuration();cfg['http_ready']=False
        with patch('mcp_http01.shutil.which',return_value='/usr/bin/nft'):self.assertTrue(http.prerequisites(cfg))
    def test_wildcard_rejected(self):
        with self.assertRaises(ValueError):configuration(alternative_names=['*.example.test'])
    def test_no_credential_required(self):
        cfg=configuration();cfg.update(enabled=True,email='admin@example.test',accept_terms=True)
        with tempfile.TemporaryDirectory() as root,patch('mcp_acme.os.path.ismount',return_value=True),patch('shutil.which',return_value='/usr/bin/fixture'):
            self.assertTrue(acme.Certificates(base=root).readiness(cfg)['ready'])
    def test_render_csr_and_rsa(self):
        with tempfile.TemporaryDirectory() as root:
            m=acme.Certificates(base=root,native=Path(root)/'native.conf');m.render(configuration(key_algorithm='rsa'))
            self.assertIn('KEYSIZE=4096',m.native.read_text());self.assertIn('OPENSSL_CNF=',m.native.read_text())
    def test_only_http_builtin_starts_responder(self):
        with tempfile.TemporaryDirectory() as root:
            m=acme.Certificates(base=root);cfg=configuration();cfg['accept_terms']=True
            with patch.object(m,'config',return_value=cfg),patch.object(m,'stage_context',return_value=Path(root)),patch('mcp_http01.Responder') as respond,patch('mcp_acme.subprocess.run',return_value=subprocess.CompletedProcess([],0)):
                self.assertEqual(m.client('issue'),0);respond.assert_called_once()
            cfg['http_mode']='external'
            with patch.object(m,'config',return_value=cfg),patch('mcp_http01.Responder') as respond,patch('mcp_acme.subprocess.run',return_value=subprocess.CompletedProcess([],0)):
                self.assertEqual(m.client('issue'),0);respond.assert_not_called()

class LifecycleTests(unittest.TestCase):
    def test_firewall_source_and_expiry(self):
        fw=http.Firewall(configuration())
        with patch.object(fw,'command',return_value=subprocess.CompletedProcess([],0,'','')) as cmd:
            fw.open();script=cmd.call_args.args[1]
        self.assertIn('192.0.2.10/32',script);self.assertIn('80 timeout 900s',script);self.assertNotIn('flush',script);self.assertNotRegex(script,r'\\btcp dport 443\\b|\\{ 443 timeout')
    def test_firewall_only_own_rules_removed(self):
        fw=http.Firewall(configuration());fw.active=True
        state={'nftables':[{'rule':{'comment':'other','handle':1}},{'rule':{'comment':fw.tag,'handle':10}}]}
        replies=[subprocess.CompletedProcess([],0,json.dumps(state),''),subprocess.CompletedProcess([],0,'','')]
        with patch.object(fw,'command',side_effect=replies) as cmd:
            fw.close();script=cmd.call_args.args[1]
        self.assertIn('handle 10',script);self.assertNotIn('handle 1\n',script);self.assertFalse(fw.active)
    def test_port_conflict_does_not_open_firewall(self):
        with tempfile.TemporaryDirectory() as root,patch('mcp_http01.shutil.which',return_value='/usr/bin/nft'),patch('mcp_http01.Server',side_effect=OSError('busy')),patch.object(http.Firewall,'open') as opened:
            with self.assertRaisesRegex(ValueError,'TCP 80'):http.Responder(configuration(),root).__enter__()
            opened.assert_not_called();self.assertFalse((Path(root)/'http-tokens').exists())
    def test_cleanup_after_client_failure(self):
        with tempfile.TemporaryDirectory() as root,patch('mcp_http01.shutil.which',return_value='/usr/bin/nft'),patch('mcp_http01.Server') as server,patch.object(http.Firewall,'open'),patch.object(http.Firewall,'close') as close:
            with self.assertRaisesRegex(ValueError,'fixture'):
                with http.Responder(configuration(),root):raise ValueError('fixture')
            close.assert_called_once();self.assertFalse((Path(root)/'http-tokens').exists());self.assertTrue(server.return_value.server_close.called)

if __name__=='__main__':unittest.main()
