#!/usr/bin/python3
"""Read-only inventory of persistent, independently managed execution environments."""
from pathlib import Path
from datetime import datetime, timezone
import os
import json
import uuid
import subprocess
import re

ROOT = Path(os.environ.get('MCP_CHROOT_ROOT', '/var/prstnt/mcp-appliance/chroots'))
CATALOG = [["ai","AI & LLM","Inference runtimes and local model execution"],["avatar","Avatar & 3D","Real-time avatar and GPU rendering tools"],["browser","Browser Automation","Chromium-based automation and authenticated browsing"],["cad","CAD & Mesh","Parametric modeling, STL inspection and mesh repair"],["cuda","GPU Compute","NVIDIA CUDA toolchain and GPU diagnostics"],["media","Video & Audio","FFmpeg, codecs, optimization and color processing"],["photo","Photography","Image processing, batch transforms and metadata"]]

class Environments:
    def start(self, body, owner):
        name=str(body.get('name',''))
        action=str(body.get('action',''))
        if not re.fullmatch('[a-z][a-z0-9-]{0,62}',name) or action not in ('check','upgrade'): raise ValueError('Invalid job')
        root=ROOT/name
        if root.is_symlink() or not root.is_dir():raise ValueError('Missing environment')
        state=Path('/var/prstnt/mcp-appliance/state/environments')
        state.mkdir(parents=True,exist_ok=True)
        ident=uuid.uuid4().hex
        job={'id':ident,'name':name,'action':action,'state':'queued','owner':owner}
        (state/(ident+'.json')).write_text(json.dumps(job))
        subprocess.run(['/usr/bin/systemd-run','--unit=mcp-env-'+ident,'--collect','/usr/bin/mcp-environment-worker',ident],check=True,timeout=15)
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
                installed.append(dict(name=name,title=title,description=description,os=release,
                    dnf_available=dnf,update_status='Not checked' if dnf else 'DNF missing',
                    update_progress=None,installed=True))
        types = {e['name'].rsplit('-f',1)[0] for e in installed}
        return dict(root=str(ROOT),installed=installed,catalog=[
            dict(id=n,title=t,description=d,installed=n in types)
            for n,t,d in CATALOG],
            note='Availability and update status are local observations; update jobs are not enabled yet.')
