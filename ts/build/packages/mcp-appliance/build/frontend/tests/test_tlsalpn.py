import hashlib,json,os,socket,ssl,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_tlsalpn as alpn
import mcp_acme as acme
import mcp_http01 as http
NAME='mcp.example.test';OTHER='alias.example.test';TOKEN='a'*43;DIGEST='12'*32

def configuration(**kw):
    return acme.normalize(dict(challenge='tls-alpn-01',primary_domain=NAME,alternative_names=[OTHER],alpn_ready=True,alpn_source_networks=['192.0.2.10'],**kw))

def generate(root,name=NAME,critical=True,extra=False,digest=DIGEST):
    path=root/'alpn-generated';path.mkdir(exist_ok=True)
    cfg=root/'openssl.cnf';cfg.write_text('[req]\ndistinguished_name=dn\n[dn]\n')
    cert,key=path/(name+'.crt.pem'),path/(name+'.key.pem')
    ext='1.3.6.1.5.5.7.1.31='+('critical,' if critical else '')+'DER:04:20:'+':'.join(digest[i:i+2] for i in range(0,64,2))
    subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:prime256v1','-nodes','-days','1','-config',str(cfg),'-subj','/CN='+name,'-addext','subjectAltName=DNS:'+name+(',DNS:extra.example.test' if extra else ''),'-addext',ext,'-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
    return cert,key

def client_context(protocols=('acme-tls/1',),version=None):
    # Self-signed, ACME-only fixture certificate, not a public HTTPS connection.
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
    if protocols is not None:ctx.set_alpn_protocols(list(protocols))
    if version:ctx.minimum_version=ctx.maximum_version=version
    return ctx

def hello(name=NAME,protocols=('acme-tls/1',)):
    incoming,outgoing=ssl.MemoryBIO(),ssl.MemoryBIO();obj=client_context(protocols).wrap_bio(incoming,outgoing,server_side=False,server_hostname=name)
    try:obj.do_handshake()
    except ssl.SSLWantReadError:pass
    return outgoing.read()

class FakeSocket:
    def __init__(self,data):self.data=data
    def settimeout(self,value):pass
    def recv(self,n):result=self.data[:n];self.data=self.data[n:];return result

class HelloTests(unittest.TestCase):
    def parse(self,data):return alpn.receive_hello(FakeSocket(data),time.monotonic()+1)[0]
    def test_real_clienthello(self):self.assertEqual(self.parse(hello()),NAME)
    def test_fragmented_records(self):
        raw=hello();body=raw[5:];a=body[:21];b=body[21:]
        self.assertEqual(self.parse(raw[:3]+len(a).to_bytes(2,'big')+a+raw[:3]+len(b).to_bytes(2,'big')+b),NAME)
    def test_case_insensitive_sni(self):self.assertEqual(self.parse(hello(NAME.upper())),NAME)
    def test_missing_sni(self):
        with self.assertRaises(ValueError):self.parse(hello(None))
    def test_no_alpn(self):
        with self.assertRaises(ValueError):self.parse(hello(protocols=None))
    def test_http_alpn(self):
        with self.assertRaises(ValueError):self.parse(hello(protocols=['http/1.1']))
    def test_multiple_protocols(self):
        with self.assertRaises(ValueError):self.parse(hello(protocols=['acme-tls/1','http/1.1']))
    def test_plain_http(self):
        with self.assertRaises(ValueError):self.parse(b'GET / HTTP/1.0\r\n\r\n')
    def test_truncated_hello(self):
        with self.assertRaises(ValueError):self.parse(hello()[:20])
    def test_oversized_record(self):
        with self.assertRaises(ValueError):self.parse(bytes.fromhex('160303ffff'))

class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'tls-challenges').mkdir();self.cfg=configuration();self.cert,self.key=generate(self.root)
    def tearDown(self):self.tmp.cleanup()
    def publish(self,name=NAME):alpn.publish(self.root,self.cfg,'deploy_challenge',name,TOKEN,DIGEST)
    def test_exact_extension_and_dns_name(self):alpn.verify_certificate(self.cert.read_text(),NAME,bytes.fromhex(DIGEST))
    def test_wrong_digest(self):
        with self.assertRaises(ValueError):alpn.verify_certificate(self.cert.read_text(),NAME,b'z'*32)
    def test_wrong_name(self):
        with self.assertRaises(ValueError):alpn.verify_certificate(self.cert.read_text(),OTHER,bytes.fromhex(DIGEST))
    def test_noncritical_extension(self):
        cert,_=generate(self.root,critical=False)
        with self.assertRaises(ValueError):alpn.verify_certificate(cert.read_text(),NAME,bytes.fromhex(DIGEST))
    def test_extra_san(self):
        cert,_=generate(self.root,extra=True)
        with self.assertRaises(ValueError):alpn.verify_certificate(cert.read_text(),NAME,bytes.fromhex(DIGEST))
    def test_key_match_required(self):
        _,other=generate(self.root,OTHER);self.key.write_bytes(other.read_bytes())
        with self.assertRaises(ssl.SSLError):self.publish()
    def test_unrequested_name(self):
        with self.assertRaises(ValueError):self.publish('bad.example.test')
    def test_symlink_refused(self):
        self.cert.rename(self.root/'outside.crt');self.cert.symlink_to(self.root/'outside.crt')
        with self.assertRaises(OSError):self.publish()
    def test_expired_certificate(self):
        with patch.object(alpn.time,'time',return_value=4102444800),self.assertRaises(ValueError):self.publish()
    def test_publish_cleanup(self):
        self.publish();self.assertEqual(len(list((self.root/'tls-challenges').iterdir())),2)
        alpn.publish(self.root,self.cfg,'clean_challenge',NAME,TOKEN,DIGEST)
        self.assertEqual(list((self.root/'tls-challenges').iterdir()),[])
    def test_idempotent_cleanup(self):alpn.publish(self.root,self.cfg,'clean_challenge',NAME,TOKEN,DIGEST)
    def test_malformed_der(self):
        for der in (b'\x30\x80',b'\x30\x82\x00\x80',b'\x30\x03\x01'):
            with self.subTest(der=der),self.assertRaises(ValueError):alpn.sequence(der)

class HandshakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.cfg=configuration();(self.root/'tls-challenges').mkdir()
        for name in (NAME,OTHER):
            generate(self.root,name);alpn.publish(self.root,self.cfg,'deploy_challenge',name,TOKEN,DIGEST)
        self.server=alpn.Server(('127.0.0.1',0),socket.AF_INET,self.root/'tls-challenges',[NAME,OTHER]);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.close_connections();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def connect(self,name=NAME,protocols=('acme-tls/1',),version=None):
        with socket.create_connection(self.server.server_address,2) as s:
            with client_context(protocols,version).wrap_socket(s,server_hostname=name) as tls:
                self.assertEqual(tls.selected_alpn_protocol(),'acme-tls/1');cert=tls.getpeercert(True)
                self.assertEqual(tls.recv(1),b'');return ssl.DER_cert_to_PEM_cert(cert)
    def test_tls12_handshake(self):alpn.verify_certificate(self.connect(version=ssl.TLSVersion.TLSv1_2),NAME,bytes.fromhex(DIGEST))
    def test_tls13_handshake(self):alpn.verify_certificate(self.connect(version=ssl.TLSVersion.TLSv1_3),NAME,bytes.fromhex(DIGEST))
    def test_multi_hostname_isolation(self):alpn.verify_certificate(self.connect(OTHER),OTHER,bytes.fromhex(DIGEST))
    def test_no_certificate_for_unknown_name(self):
        with self.assertRaises(OSError):self.connect('unknown.example.test')
    def test_no_certificate_for_other_alpn(self):
        with self.assertRaises(OSError):self.connect(protocols=['http/1.1'])
    def test_no_certificate_after_cleanup(self):
        alpn.publish(self.root,self.cfg,'clean_challenge',NAME,TOKEN,DIGEST)
        with self.assertRaises(OSError):self.connect()
    def test_modified_bundle_rejected(self):
        row=json.loads((self.root/'tls-challenges'/(hashlib.sha256(NAME.encode()).hexdigest()+'.json')).read_text());(self.root/'tls-challenges'/(row['slot']+'.pem')).write_text('modified')
        with self.assertRaises(OSError):self.connect()

class IntegrationTests(unittest.TestCase):
    def test_enabled(self):self.assertTrue(next(x for x in acme.certificate_form.CHALLENGES if x['value']=='tls-alpn-01')['enabled'])
    def test_fields_do_not_cross_methods(self):
        cfg=configuration(credential='ignored',ad_host='ignored',http_ready=True,http_public_access=True)
        self.assertEqual(cfg['credential'],'');self.assertFalse(cfg['http_ready']);self.assertFalse(cfg['http_public_access'])
    def test_wildcards_rejected(self):
        with self.assertRaises(ValueError):acme.normalize({'challenge':'tls-alpn-01','alternative_names':['*.example.test']})
    def test_invalid_boolean(self):
        with self.assertRaises(ValueError):acme.normalize({'challenge':'tls-alpn-01','alpn_ready':'yes'})
    def test_explicit_sources_required(self):
        cfg=configuration();cfg['alpn_source_networks']=[];self.assertTrue(alpn.prerequisites(cfg))
    def test_443_firewall_not_80(self):
        cfg=configuration();f=http.Firewall({'http_source_networks':cfg['alpn_source_networks'],'http_public_access':False},port=443,prefix='mcp-alpn01')
        with patch.object(f,'command',return_value=subprocess.CompletedProcess([],0,'','')) as run:f.open()
        text=run.call_args.args[1];self.assertIn('443 timeout 900s',text);self.assertNotIn('80 timeout',text);self.assertIn('192.0.2.10/32',text)
    def test_port_conflict_cleanup(self):
        cfg=configuration()
        with tempfile.TemporaryDirectory() as td,patch.object(alpn,'prerequisites',return_value=[]),patch.object(alpn,'Server',side_effect=OSError),patch.object(http.Firewall,'open') as firewall:
            with self.assertRaisesRegex(ValueError,'TCP 443'):alpn.Responder(cfg,td).__enter__()
            self.assertEqual(list(Path(td).iterdir()),[]);firewall.assert_not_called()
    def test_worker_uses_responder(self):
        with tempfile.TemporaryDirectory() as td:
            m=acme.Certificates(base=td,native=Path(td)/'native.conf');cfg=configuration();cfg['accept_terms']=True
            with patch.object(m,'config',return_value=cfg),patch.object(m,'stage_context',return_value=Path(td)),patch.object(alpn,'Responder') as respond,patch.object(acme.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
                self.assertEqual(m.client('force'),0)
            self.assertEqual(respond.call_count,1);self.assertIn('--alpn',run.call_args.args[0]);self.assertIn('--force',run.call_args.args[0])

if __name__=='__main__':unittest.main()
