"""Persistent inventory storage shared by the console and MCP runtime."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
BASE=Path('/var/prstnt/mcp-appliance')
PATH=BASE/'config/hosts.json'
LEGACY=Path('/etc/mcp-appliance/hosts.json')

def validate(raw):
    value=json.loads(raw or '{}')
    if not isinstance(value,dict): raise ValueError('Inventory must be a JSON object.')
    for section in ('hosts','groups'):
        value.setdefault(section,{})
        if not isinstance(value[section],dict): raise ValueError(section+' must be a JSON object.')
        for name,row in value[section].items():
            if not re.fullmatch(r'[a-z0-9._-]+',name) or name in ('__proto__','constructor','prototype'): raise ValueError('Invalid '+section+' name: '+name)
            if not isinstance(row,dict): raise ValueError('Each inventory entry must be a JSON object.')
    for alias,row in value['hosts'].items():
        for field in ('address',):
            text=row.get(field)
            if not isinstance(text,str) or not text or any(c.isspace() or ord(c)<32 for c in text) or text.startswith('-'): raise ValueError(alias+': '+field+' must be nonempty text without spaces or options.')
        username=row.get('username','')
        if username is not None and (not isinstance(username,str) or any(c.isspace() or ord(c)<32 for c in username) or username.startswith('-')): raise ValueError(alias+': invalid legacy username.')
        if row.get('platform') not in ('linux','windows'): raise ValueError(alias+': platform must be linux or windows.')
        for field in ('hostname','identity_file'):
            if row.get(field) is not None and not isinstance(row[field],str): raise ValueError(alias+': invalid '+field)
        if row.get('identity_file') and not Path(row['identity_file']).is_absolute(): raise ValueError(alias+': identity key path must be absolute.')
    for name,row in value['groups'].items():
        members=row.get('hosts',[])
        if not isinstance(members,list) or any(not isinstance(x,str) or x not in value['hosts'] for x in members): raise ValueError(name+': group members must refer to existing hosts.')
    return value

def encode(value): return json.dumps(value,indent=2)+'\n'

def atomic(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

class Inventory:
    def __init__(self,path=PATH,legacy=LEGACY): self.path,self.legacy=Path(path),Path(legacy)
    def ensure(self):
        if not self.path.exists():
            raw=self.legacy.read_text() if self.legacy.is_file() else '{}'
            atomic(self.path,encode(validate(raw)))
        return self.path
    def read(self):
        raw=self.ensure().read_text();validate(raw)
        return {'name':'hosts','value':raw,'revision':hashlib.sha256(raw.encode()).hexdigest()}
    def save(self,raw,revision=None):
        value=validate(raw);self.ensure()
        lock=self.path.with_suffix('.lock')
        with lock.open('a') as stream:
            os.chmod(lock,0o600);fcntl.flock(stream,fcntl.LOCK_EX)
            previous=self.read()
            if revision and revision.strip('"')!=previous['revision']: raise ValueError('Inventory changed in another session. Refresh before saving; your entries have not been overwritten.')
            changed=json.loads(previous['value'])!=value
            if changed: atomic(self.path,encode(value))
            return {'ok':True,'changed':changed,**self.read()}

def apply_runtime():
    """Restart only an active MCP runtime; never start a stopped runtime."""
    try:
        state=subprocess.run(['/usr/bin/systemctl','is-active','mcp-runtime.service'],capture_output=True,text=True,timeout=5)
        if state.stdout.strip()!='active': return 'Inventory saved. Start the MCP runtime to use it.'
        p=subprocess.run(['/usr/bin/systemctl','try-restart','mcp-runtime.service'],capture_output=True,text=True,timeout=25)
        if p.returncode: return 'Inventory saved, but MCP could not restart. Review MCP status before using the new inventory.'
        return 'MCP runtime restarted to load the saved inventory.'
    except (OSError,subprocess.SubprocessError): return 'Inventory saved; runtime restart could not be verified. Review MCP status.'
