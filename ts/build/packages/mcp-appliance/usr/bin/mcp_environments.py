#!/usr/bin/python3
"""Read-only inventory of persistent, independently managed execution environments."""
from pathlib import Path
from datetime import datetime, timezone
import os
import json
import uuid
import subprocess
import re
import fcntl

ROOT = Path(os.environ.get('MCP_CHROOT_ROOT', '/var/prstnt/mcp-appliance/chroots'))
CATALOG = [["ai","AI & LLM","Inference runtimes and local model execution"],["avatar","Avatar & 3D","Real-time avatar and GPU rendering tools"],["browser","Browser Automation","Chromium-based automation and authenticated browsing"],["cad","CAD & Mesh","Parametric modeling, STL inspection and mesh repair"],["cuda","GPU Compute","NVIDIA CUDA toolchain and GPU diagnostics"],["media","Video & Audio","FFmpeg, codecs, optimization and color processing"],["photo","Photography","Image processing, batch transforms and metadata"]]

class Environments:
    def sources(self):
        file=Path('/var/prstnt/mcp-appliance/config/package-sources.json')
        try: saved=json.loads(file.read_text())
        except (OSError,ValueError): saved={}
        try: lines=Path('/etc/thinstation.defaults').read_text().splitlines()
        except OSError: lines=[]
        def default(key):
            return next((x.partition('=')[2].strip().strip('"') for x in lines if x.startswith(key+'=')),'')
        return {'fedora_url':saved.get('fedora_url',default('MCP_PACKAGE_FEDORA_URL')),'updates_url':saved.get('updates_url',default('MCP_PACKAGE_UPDATES_URL')),'fallback':False,'fallback_supported':False,'source':'persistent' if saved else 'build defaults'}
    def save_sources(self, body):
        from urllib.parse import urlsplit
        result={}
        for key in ('fedora_url','updates_url'):
            val=str(body.get(key,'')).strip()
            if len(val)>1024:raise ValueError('Repository URL too long')
            if val:
                url=urlsplit(val)
                if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment:raise ValueError('Repository URL must be HTTPS without credentials or fragments')
            result[key]=val
        if body.get('fallback'):raise ValueError('Automatic fallback is not yet supported')
        file=Path('/var/prstnt/mcp-appliance/config/package-sources.json')
        file.parent.mkdir(parents=True,exist_ok=True)
        tmp=file.with_suffix('.tmp')
        tmp.write_text(json.dumps(result))
        tmp.chmod(0o600)
        tmp.replace(file)
        return self.sources()
    def start(self, body, owner):
        name=str(body.get('name',''))
        action=str(body.get('action',''))
        if not re.fullmatch('[a-z][a-z0-9-]{0,62}',name) or action not in ('check','upgrade'): raise ValueError('Invalid job')
        # Chroots are disposable; recovery is a catalog-backed rebuild, not an in-place snapshot.
        root=ROOT/name
        if root.is_symlink() or not root.is_dir():raise ValueError('Missing environment')
        state=Path('/var/prstnt/mcp-appliance/state/environments')
        state.mkdir(parents=True,exist_ok=True)
        with (state/'.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            for previous in state.glob('*.json'):
                try: old=json.loads(previous.read_text())
                except (OSError, ValueError): continue
                if old.get('name')==name and old.get('state') in ('queued','running'):
                    raise ValueError('An operation is already active for this environment')
            return self._schedule(name,action,owner,state)

    def _schedule(self,name,action,owner,state):
        ident=uuid.uuid4().hex
        job={'id':ident,'name':name,'action':action,'state':'queued','owner':owner}
        (state/(ident+'.json')).write_text(json.dumps(job))
        try:
            subprocess.run(['/usr/bin/systemd-run','--unit=mcp-env-'+ident,'--collect','/usr/bin/mcp-environment-worker',ident],check=True,timeout=15,capture_output=True)
        except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired):
            job['state']='failed'
            (state/(ident+'.json')).write_text(json.dumps(job))
            raise ValueError('Environment worker could not start')
        return job
    def job(self, ident):
        if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid job ID')
        folder=Path('/var/prstnt/mcp-appliance/state/environments')
        file=folder/(ident+'.json')
        if not file.is_file():raise ValueError('Job missing')
        job=json.loads(file.read_text())
        log=folder/(ident+'.log')
        job['log_tail']=log.read_text(errors='replace')[-12000:] if log.exists() else ''
        return job

    def status(self):
        known = {name:(title,desc) for name,title,desc in CATALOG}
        installed = []
        if ROOT.is_dir():
            for path in sorted(ROOT.iterdir()):
                if not path.is_dir() or path.is_symlink(): continue
                name = path.name
                kind = name.rsplit('-f',1)[0]
                title,description = known.get(kind,(name,'Custom persistent execution environment'))
                dnf = (path/'usr/bin/dnf').exists() or (path/'usr/bin/dnf5').exists()
                release = 'Unknown'
                try:
                    data=(path/'etc/os-release').read_text(errors='replace')
                    release=next((line.split('=',1)[1].strip().strip('"') for line in data.splitlines() if line.startswith('PRETTY_NAME=')),release)
                except OSError: pass
                history=[]
                for jobfile in (Path('/var/prstnt/mcp-appliance/state/environments')).glob('*.json'):
                    try: entry=json.loads(jobfile.read_text())
                    except (OSError,ValueError): continue
                    if entry.get('name')==name:history.append(entry)
                latest=history[-1] if history else {}
                installed.append(dict(name=name,title=title,description=description,os=release,
                    dnf_available=dnf,update_status=latest.get('state','Not checked') if dnf else 'DNF missing',
                    update_progress=latest.get('progress'),latest_job=latest.get('id'),installed=True))
        types = {e['name'].rsplit('-f',1)[0] for e in installed}
        return dict(root=str(ROOT),installed=installed,sources=self.sources(),catalog=[
            dict(id=n,title=t,description=d,installed=n in types)
            for n,t,d in CATALOG],
            note='Chroots contain no durable user data. Recovery uses removal and redeployment from an environment definition; automated rebuild remains under development.')
