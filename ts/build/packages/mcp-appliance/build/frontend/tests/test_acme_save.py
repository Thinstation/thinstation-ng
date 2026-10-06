import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_acme as acme

class SaveTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.manager=acme.Certificates(base=self.root,native=self.root/'native.conf')
  self.cfg=acme.normalize({'enabled':False,'automatic':False,'directory_url':'ca.example.test/directory','primary_domain':'mcp.example.test','challenge':'http-01','http_mode':'standalone','http_source_networks':['192.0.2.10']})
 def tearDown(self):self.temp.cleanup()
 def test_save_confirms_exact_persistent_configuration(self):
  with patch.object(acme.os.path,'ismount',return_value=True),patch.object(self.manager,'status',return_value={'config':self.cfg}),patch.object(acme,'command') as commands:
   result=self.manager.save(self.cfg)
  self.assertTrue(result['ok']);self.assertEqual(result['config'],json.loads(self.manager.settings.read_text()))
  self.assertEqual(result['config']['http_source_networks'],['192.0.2.10/32']);commands.assert_not_called()
  self.assertEqual(self.manager.settings.stat().st_mode&0o777,0o600)
 def test_status_failure_does_not_hide_successful_save(self):
  with patch.object(acme.os.path,'ismount',return_value=True),patch.object(self.manager,'status',side_effect=ValueError('fixture diagnostic failure')):
   result=self.manager.save(self.cfg)
  self.assertTrue(result['ok']);self.assertIsNone(result['status']);self.assertIn('saved',result['status_warning'])
  self.assertEqual(result['config'],acme.Certificates(base=self.root,native=self.manager.native).config())
 def test_invalid_values_cannot_overwrite_previous_settings(self):
  acme.atomic(self.manager.settings,json.dumps(self.cfg))
  with patch.object(acme.os.path,'ismount',return_value=True),self.assertRaisesRegex(ValueError,'Primary DNS name'):
   self.manager.save({**self.cfg,'primary_domain':'shortname'})
  self.assertEqual(json.loads(self.manager.settings.read_text()),self.cfg)
 def test_alternative_name_error_identifies_field(self):
  with self.assertRaisesRegex(ValueError,'Alternative DNS names'):
   acme.normalize({**self.cfg,'alternative_names':['shortname']})
 def test_persistent_write_failure_restores_generated_configuration(self):
  self.manager.native.write_text('old native settings')
  acme.atomic(self.manager.settings,json.dumps(self.cfg));old=self.manager.settings.read_bytes();real=acme.atomic
  def fail(path,*args,**kwargs):
   if Path(path)==self.manager.settings:raise OSError('fixture full disk')
   return real(path,*args,**kwargs)
  with patch.object(acme.os.path,'ismount',return_value=True),patch.object(acme,'atomic',side_effect=fail),self.assertRaisesRegex(ValueError,'previous configuration was retained'):
   self.manager.save({**self.cfg,'primary_domain':'new.example.test'})
  self.assertEqual(self.manager.native.read_text(),'old native settings');self.assertEqual(self.manager.settings.read_bytes(),old)
 def test_first_save_failure_does_not_create_runtime_configuration(self):
  real=acme.atomic
  def fail(path,*args,**kwargs):
   if Path(path)==self.manager.settings:raise OSError('fixture read-only')
   return real(path,*args,**kwargs)
  with patch.object(acme.os.path,'ismount',return_value=True),patch.object(acme,'atomic',side_effect=fail),self.assertRaises(ValueError):self.manager.save(self.cfg)
  self.assertFalse(self.manager.native.exists());self.assertFalse(self.manager.settings.exists())
 def test_normalized_save_is_idempotent(self):
  with patch.object(acme.os.path,'ismount',return_value=True),patch.object(self.manager,'status',return_value={}):
   first=self.manager.save(self.cfg);second=self.manager.save(first['config'])
  self.assertEqual(first['config'],second['config'])
 def test_save_never_requests_certificate(self):
  with patch.object(acme.os.path,'ismount',return_value=True),patch.object(self.manager,'status',return_value={}),patch.object(self.manager,'action') as action,patch.object(self.manager,'client') as client:
   self.manager.save(self.cfg)
  action.assert_not_called();client.assert_not_called()
