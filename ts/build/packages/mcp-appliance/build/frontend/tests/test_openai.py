import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
from mcp_operator import OperatorAPI
from mcp_openai import OpenAITunnel, normalize_tunnel, health_summary

TID='tunnel_0123456789abcdef0123456789abcdef'
KEY='sk-test-not-a-real-credential-0123456789'

class TunnelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.op=OperatorAPI({'BASE':self.base})
        self.t=OpenAITunnel(self.op,base=self.base)
        self.body={'name':'ChatGPT test','tunnel_id':TID,'api_key':KEY,'confirm_full_access':True,'confirm_dedicated_tunnel':True}
    def tearDown(self):self.tmp.cleanup()
    def save(self,**values):
        body={**self.body,**values}
        def encrypt(argv,**kwargs):
            self.assertNotIn(KEY,' '.join(argv));self.assertEqual(kwargs['input'],KEY.encode())
            Path(argv[-1]).write_bytes(b'fixture ciphertext, not plaintext');return subprocess.CompletedProcess(argv,0,b'',b'')
        original=Path.exists
        def exists(path):return str(path)=='/dev/tpmrm0' or original(path)
        with patch('mcp_openai.os.path.ismount',return_value=True),patch.object(self.t,'_unit_state',return_value='inactive'),patch('mcp_openai.subprocess.run',side_effect=encrypt),patch('pathlib.Path.exists',exists):
            return self.t.save(body)
    def test_tunnel_id_and_openai_url(self):
        self.assertEqual(normalize_tunnel(TID),TID)
        self.assertEqual(normalize_tunnel('https://api.openai.com/v1/tunnel/'+TID),TID)
        self.assertEqual(normalize_tunnel('https://platform.openai.com/settings/tunnels/'+TID),TID)
    def test_unrelated_urls_and_shell_text_rejected(self):
        for value in ['https://evil.example/'+TID,'https://api.openai.com/oauth/callback','http://api.openai.com/'+TID,'https://user:secret@api.openai.com/'+TID,'https://api.openai.com:444/'+TID,'$(touch /tmp/no)','tunnel_short']:
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_tunnel(value)
    def test_save_never_starts_a_tunnel_and_does_not_echo_key(self):
        with patch.object(self.t,'_control') as control:
            result=self.save();control.assert_not_called()
        self.assertTrue(result['ok']);self.assertFalse(result['status']['enabled'])
        self.assertNotIn(KEY,json.dumps(result))
        for p in self.base.rglob('*'):
            if p.is_file():self.assertNotIn(KEY.encode(),p.read_bytes())
        self.assertEqual((self.t.current/'api-key.cred').stat().st_mode&0o777,0o600)
    def test_both_access_confirmations_required(self):
        for field in ['confirm_full_access','confirm_dedicated_tunnel']:
            with self.subTest(field=field),self.assertRaises(ValueError):self.save(**{field:False})
    def test_missing_persistence_rejected(self):
        with patch('mcp_openai.os.path.ismount',return_value=False),self.assertRaisesRegex(ValueError,'persistent'):self.t.save(self.body)
    def test_tpm_failure_does_not_publish_profile(self):
        original=Path.exists
        with patch('mcp_openai.os.path.ismount',return_value=True),patch.object(self.t,'_unit_state',return_value='inactive'),patch('pathlib.Path.exists',lambda p: str(p)=='/dev/tpmrm0' or original(p)),patch('mcp_openai.subprocess.run',return_value=subprocess.CompletedProcess([],1,b'',b'sensitive failure')),self.assertRaisesRegex(ValueError,'encrypted'):
            self.t.save(self.body)
        self.assertFalse(self.t.current.exists())
    def test_edits_blocked_while_connected(self):
        with patch('mcp_openai.os.path.ismount',return_value=True),patch.object(self.t,'_unit_state',return_value='active'),self.assertRaisesRegex(ValueError,'Disconnect'):self.t.save(self.body)
    def test_keep_saved_key_but_require_key_for_new_tunnel(self):
        self.save()
        with patch('mcp_openai.os.path.ismount',return_value=True),patch.object(self.t,'_unit_state',return_value='inactive'):
            self.t.save({**self.body,'api_key':''})
            with self.assertRaisesRegex(ValueError,'runtime key'):self.t.save({**self.body,'api_key':'','tunnel_id':'tunnel_abcdef0123456789'})
    def test_connect_requires_runtime_and_disconnect_removes_autostart(self):
        self.save()
        with self.assertRaisesRegex(ValueError,'component'):self.t.action('connect')
        self.t.component.mkdir(parents=True);(self.t.component/'tunnel-client-runtime').write_text('fixture');(self.t.component/'verified.json').write_text('{}')
        with patch.object(self.t,'_control') as control,patch.object(self.t,'_unit_state',return_value='inactive'):
            self.t.action('connect');self.assertTrue(self.t.enabled.exists());control.assert_called_with('start')
            self.t.action('disconnect');self.assertFalse(self.t.enabled.exists());control.assert_called_with('stop')
    def test_runtime_download_checksum_failure_never_executes_binary(self):
        def download(argv,**kwargs):
            Path(argv[argv.index('-o')+1]).write_bytes(b'untrusted');return subprocess.CompletedProcess(argv,0,b'',b'')
        with patch('mcp_openai.os.path.ismount',return_value=True),patch('mcp_openai.subprocess.run',side_effect=download),self.assertRaisesRegex(ValueError,'checksum'):
            self.t.install_runtime()
        self.assertFalse(self.t.component.exists())
    def test_service_credentials_not_commandline_and_no_listener(self):
        unit=(Path(__file__).resolve().parents[3]/'usr/lib64/systemd/system/mcp-openai-tunnel.service').read_text()
        self.assertIn('LoadCredentialEncrypted=openai-api-key:',unit)
        self.assertIn('ConditionPathExists=',unit)
        source=(Path(__file__).resolve().parents[3]/'usr/bin/mcp_openai.py').read_text()
        self.assertIn('--control-plane.api-key=file:',source)
        self.assertIn('--control-plane.poll-channel=main',source)
        self.assertIn('--harpoon.hosts-include-private=false',source)
        self.assertIn('--health.unix-socket=',source)

class HealthTests(unittest.TestCase):
    def fixture(self,**details):
        stamp=datetime.datetime.fromtimestamp(1000,datetime.timezone.utc).isoformat()
        return {'schema_version':1,'live':True,'ready':True,'snapshot_at':stamp,'components':{'control-plane':{'status':'ok','state':'polling','details':{'last_success':stamp,**details}}}}
    def test_live_and_ready_are_not_connected(self):
        s=self.fixture();s['components']={}
        self.assertEqual(health_summary('active',True,s,1005)['state'],'connecting')
    def test_successful_poll_is_distinct_from_request(self):
        v=health_summary('active',True,self.fixture(),1005)
        self.assertEqual(v['state'],'connected');self.assertFalse(v['request_evidence'])
    def test_auth_rejection_is_actionable(self):
        s=self.fixture(http_status=401);s['components']['control-plane']['status']='degraded'
        v=health_summary('active',True,s,1005);self.assertEqual(v['state'],'retrying');self.assertIn('runtime key',v['detail'])
    def test_stale_health_and_old_success_not_green(self):
        self.assertEqual(health_summary('active',True,self.fixture(),1035)['state'],'stale')
        s=self.fixture();s['components']['control-plane']['details']['last_success']='1970-01-01T00:01:00+00:00'
        self.assertEqual(health_summary('active',True,s,1005)['state'],'connecting')
    def test_disabled_or_failed_not_connected(self):
        self.assertEqual(health_summary('inactive',False,self.fixture(),1005)['state'],'disconnected')
        self.assertEqual(health_summary('failed',True,self.fixture(),1005)['state'],'service_unavailable')
    def test_request_and_delivery_kept_separate(self):
        s=self.fixture();s['components']['queue']={'details':{'last_enqueue':'1970-01-01T00:16:41Z'}}
        v=health_summary('active',True,s,1005);self.assertTrue(v['request_evidence']);self.assertIsNone(v['last_response_accepted'])

if __name__=='__main__':unittest.main()
