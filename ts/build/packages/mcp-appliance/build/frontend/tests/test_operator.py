import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
from mcp_operator import OperatorAPI

class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.inventory=self.base/'hosts.json';self.inventory.write_text('{"hosts":{},"groups":{}}')
        self.state={'mcp_service':'active','mcp_runtime':'running pid=1','mcp_selected':{}}
        self.api=OperatorAPI({'BASE':self.base,'FILES':{'hosts':self.inventory},'connection_info':lambda:{'url':'https://appliance.example/mcp','token':'shared-secret'},'status':lambda:self.state,'generation_status':lambda:{'generations':[]},'vault_status':lambda:{'locked':True,'available':True,'credentials':[]}})
    def tearDown(self):self.tmp.cleanup()
    def create(self,**extra):
        with patch('mcp_operator.os.path.ismount',return_value=True):
            return self.api.create_connection({'name':'Workstation','application':'vscode','confirm_full_access':True,**extra})
    def test_secret_is_one_time_only(self):
        r=self.create();self.assertNotIn(r['token'],self.api.clients_file.read_text());self.assertNotIn('token_hash',json.dumps(self.api.connections()));self.assertNotIn('shared-secret',json.dumps(self.api.connections()));self.assertEqual(self.api.clients_file.stat().st_mode&0o777,0o600)
    def test_independent_auth_and_revocation(self):
        a=self.create();b=self.create(name='Second');identifier=a['connection']['id']
        self.assertEqual(self.api.authenticate_client('Bearer '+a['token']),identifier)
        self.assertIsNone(self.api.authenticate_client('Bearer '+a['token']+'x'))
        self.api.revoke_connection({'id':identifier});self.api.revoke_connection({'id':identifier})
        self.assertIsNone(self.api.authenticate_client('Bearer '+a['token']))
        self.assertEqual(self.api.authenticate_client('Bearer '+b['token']),b['connection']['id'])
    def test_access_acknowledgment_required(self):
        with self.assertRaises(ValueError):self.create(confirm_full_access=False)
    def test_persistence_required(self):
        with patch('mcp_operator.os.path.ismount',return_value=False):
            with self.assertRaises(ValueError):self.api.create_connection({'name':'x','confirm_full_access':True})
    def test_unsupported_tunnel_is_not_provisioned(self):
        with self.assertRaises(ValueError):self.create(method='tunnel')
    def test_duplicate_client_names_rejected(self):
        self.create()
        with self.assertRaises(ValueError):self.create(name='WORKSTATION')
    def test_corrupt_registry_fails_closed(self):
        self.create();self.api.clients_file.write_text('broken')
        self.assertIsNone(self.api.authenticate_client('Bearer mcp_invalid'))
        with self.assertRaises(ValueError):self.api.connections()
    def test_gateway_evidence_not_tool_result(self):
        r=self.create();self.api.record_gateway_request(r['connection']['id'],200)
        data=self.api.connections();self.assertEqual(data['clients'][0]['last_http_status'],200);self.assertIn('not a tool-result check',data['events'][0]['detail'])
    def test_probe_invalidated_after_runtime_changes(self):
        self.api.last_probe={'responding':True};self.api.last_probe_runtime=('active','running pid=1')
        self.assertIsNotNone(self.api.runtime()['probe']);self.state['mcp_runtime']='running pid=2';self.assertIsNone(self.api.runtime()['probe'])
    def test_version_metadata(self):
        info=self.api.version_metadata('thinstation-mcp-build-178');self.assertEqual(info['version'],'Build 178');self.assertEqual(info['family'],'thinstation-mcp');self.assertIsNone(self.api.version_metadata('other-abcdef')['build_number'])

if __name__=='__main__':unittest.main()
