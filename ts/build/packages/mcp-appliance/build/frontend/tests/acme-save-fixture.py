"""Loopback-only browser fixture using real save/normalization and temporary files.

No host configuration, CA operations, or real credentials are accessed.
"""
import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'usr/bin'))
import mcp_acme as acme

web=Path(sys.argv[1]).resolve()
workspace=tempfile.TemporaryDirectory(prefix='acme-save-browser-')
base=Path(workspace.name)
manager=acme.Certificates(base=base,native=base/'native.conf')
acme.atomic(base/'config/hosts.json',json.dumps({'hosts':{'ad':{'platform':'windows','hostname':'dc.example.test','address':'192.0.2.10'}},'groups':{'windows':{'hosts':['ad']}}}))
controls={'reject_save':False,'fail_status':False,'malformed_ack':False}
counters={'save_attempts':0,'actions':0,'reads':0}

def status():
 if controls['fail_status']:raise ValueError('Fixture diagnostics unavailable')
 cfg=manager.config()
 return {'config':cfg,'settings_saved':manager.settings.exists(),'appliance_identity':acme.appliance_identity('fixture','search example.test'),'certificate':{'present':False,'valid_now':False,'self_issued':False,'trust_note':'Isolated fixture.'},'job':{'state':'idle','message':'No requests in this fixture.'},'readiness':{'ready':False,'issues':['Fixture does not issue certificates.'],'warnings':[]},'provider_ready':False,'dns_hooks':[],'credentials':[{'name':'fixture-ad','type':'active-directory','scopes':['acme'],'allowed_hosts':['group:windows'],'domain':'example.test'}],'ad_inventory_hosts':manager.inventory_candidates(),'challenge_types':acme.certificate_form.CHALLENGES,'timer_active':False,'schedule':'Fixture only','vault_locked':True,'http_webroot':'/fixture/http-01','dns_hook_directory':'/fixture/hooks'}
manager.status=status

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send_json(self,value,code=200):
  raw=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  try:
   if self.path=='/api/registration':return self.send_json({'registered':True})
   if self.path=='/api/issue':return self.send_json({'text':''})
   if self.path=='/api/session':return self.send_json({'user':{'username':'fixture-admin','role':'admin'},'csrf':'fixture-only'})
   if self.path=='/api/health':return self.send_json(None)
   if self.path=='/api/operator/certificates':
    counters['reads']+=1;return self.send_json(status())
   if self.path=='/__fixture':return self.send_json({'counters':counters,'saved':json.loads(manager.settings.read_text()) if manager.settings.exists() else None,'runtime_settings':manager.native.read_text() if manager.native.exists() else ''})
   f=(web/(self.path.lstrip('/') if self.path!='/' else 'index.html')).resolve();f.relative_to(web)
   data=f.read_bytes();self.send_response(200);self.send_header('Content-Type','text/javascript' if f.suffix=='.js' else 'text/css' if f.suffix=='.css' else 'image/svg+xml' if f.suffix=='.svg' else 'text/html');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  except ValueError as exc:return self.send_json({'error':str(exc)},503)
  except OSError:return self.send_json({'error':'Not found'},404)
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or '{}')
  if self.path=='/__fixture':
   controls.update({k:bool(v) for k,v in body.items() if k in controls});return self.send_json({'ok':True})
  if self.path=='/api/operator/certificates/action':
   counters['actions']+=1;return self.send_json({'error':'Issuance forbidden in fixture.'},403)
  if self.path=='/api/operator/certificates/save':
   counters['save_attempts']+=1
   if controls['reject_save']:return self.send_json({'error':'Fixture persistent storage is read-only.'},503)
   if controls['malformed_ack']:return self.send_json({'ok':True})
   try:
    with patch.object(acme.os.path,'ismount',return_value=True):result=manager.save(body)
    return self.send_json(result)
   except ValueError as exc:return self.send_json({'error':str(exc)},400)
  return self.send_json({'error':'Not found'},404)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
print(json.dumps({'port':server.server_port}),flush=True)
try:server.serve_forever()
finally:server.server_close();workspace.cleanup()
