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
STATE = Path('/var/prstnt/mcp-appliance/state/environments')
MANIFESTS = Path('/var/prstnt/mcp-appliance/config/environment-manifests')
CATALOG = [["ai","AI & LLM","Inference runtimes and local model execution"],["avatar","Avatar & 3D","Real-time avatar and GPU rendering tools"],["browser","Browser Automation","Chromium-based automation and authenticated browsing"],["cad","CAD & Mesh","Parametric modeling, STL inspection and mesh repair"],["cuda","GPU Compute","NVIDIA CUDA toolchain and GPU diagnostics"],["media","Video & Audio","FFmpeg, codecs, optimization and color processing"],["photo","Photography","Image processing, batch transforms and metadata"],["wireshark","Network Analysis","Wireshark CLI and capture analysis tools"]]

KEY_PACKAGES = {
 'ai':['python3','llama.cpp','ollama'], 'avatar':['blender','python3','ffmpeg'],
 'browser':['chromium','firefox','playwright'], 'cad':['freecad','blender','meshlab'],
 'cuda':['nvidia-smi','nvcc','python3'], 'media':['ffmpeg','ffprobe','mediainfo'],
 'photo':['imagemagick','exiftool','darktable'], 'wireshark':['wireshark-cli','tshark','tcpdump']
}
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
        if not re.fullmatch('[a-z][a-z0-9-]{0,62}',name) or action not in ('check','update','rebuild'): raise ValueError('Invalid job')
        # Chroots are disposable. Rebuilds require an explicit, validated package manifest.
        root=ROOT/name
        if action=='rebuild':
            manifest=Path('/var/prstnt/mcp-appliance/config/environment-manifests')/(name+'.json')
            if not manifest.is_file():raise ValueError('No approved environment manifest; rebuild blocked')
        if root.is_symlink() or (not root.is_dir() and action!='rebuild'):raise ValueError('Missing environment')
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
        job={'id':ident,'name':name,'action':action,'state':'queued','owner':owner,'created_at':datetime.now(timezone.utc).isoformat()}
        (state/(ident+'.json')).write_text(json.dumps(job))
        try:
            subprocess.run(['/usr/bin/systemd-run','--unit=mcp-env-'+ident,'--collect','/usr/bin/python3','/usr/bin/mcp-environment-worker',ident],check=True,timeout=15,capture_output=True)
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
        # One pass over job metadata, not one full rescan per chroot.
        known = {name:(title,desc) for name,title,desc in CATALOG}
        history = []
        for jobfile in STATE.glob('*.json'):
            if jobfile.is_symlink():
                continue
            try:
                entry = json.loads(jobfile.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(entry, dict) or not re.fullmatch(r'[a-f0-9]{32}', str(entry.get('id', ''))):
                continue
            history.append(entry)
        history.sort(key=lambda entry: str(entry.get('created_at', '')))
        by_id = {entry['id']:entry for entry in history}
        by_name = {}
        for entry in history:
            by_name.setdefault(str(entry.get('name', '')), []).append(entry)
        installed, staging = [], []
        if ROOT.is_dir():
            for path in sorted(ROOT.iterdir()):
                if path.is_symlink() or not path.is_dir():
                    continue
                name = path.name
                if name.startswith('.'):
                    kind = 'previous' if name.startswith('.previous-') else 'stage' if name.startswith('.stage-') else 'internal'
                    ident = name.partition('-')[2]
                    previous = by_id.get(ident, {})
                    try:
                        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                    except OSError:
                        modified = None
                    staging.append(dict(name=name, kind=kind, state=previous.get('state'),
                        environment=previous.get('name'), latest_job=previous.get('id'), modified_at=modified))
                    continue
                kind = name.rsplit('-f', 1)[0]
                title, description = known.get(kind, (name, 'Custom persistent execution environment'))
                dnf = (path/'usr/bin/dnf').exists() or (path/'usr/bin/dnf5').exists()
                apt = (path/'usr/bin/apt-get').exists()
                manager = 'dnf' if dnf else ('apt' if apt else 'none')
                manifest_file = MANIFESTS/(name+'.json')
                try:
                    manifest = json.loads(manifest_file.read_text()) if not manifest_file.is_symlink() else {}
                except (OSError, ValueError):
                    manifest = {}
                if not isinstance(manifest, dict):
                    manifest = {}
                packages = manifest.get('packages', [])
                definition_ready = bool(isinstance(packages, list) and 0 < len(packages) <= 200
                    and all(isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9_+][A-Za-z0-9_+.-]{0,99}', item) for item in packages)
                    and re.fullmatch(r'[a-z][a-z0-9-]{0,62}', name))
                keys = manifest.get('key_packages', KEY_PACKAGES.get(kind, []))
                keys = [item for item in keys if isinstance(item, str)] if isinstance(keys, list) else []
                release = 'Unknown'
                try:
                    text = (path/'etc/os-release').read_text(errors='replace')
                    release = next((line.split('=',1)[1].strip().strip('"') for line in text.splitlines() if line.startswith('PRETTY_NAME=')), release)
                except OSError:
                    pass
                records = by_name.get(name, [])
                latest = records[-1] if records else {}
                checks = [entry for entry in records if entry.get('action') == 'check' and entry.get('state') in ('completed', 'succeeded')]
                check = checks[-1] if checks else {}
                # Mutations invalidate a prior package-state observation, including
                # failed updates which may have partially changed the environment.
                if check and any(entry.get('action') in ('update', 'rebuild')
                                 and str(entry.get('created_at', '')) > str(check.get('created_at', '')) for entry in records):
                    check = {}
                installed.append(dict(name=name, title=title, description=description, os=release,
                    dnf_available=dnf, apt_available=apt, package_manager=manager, key_packages=keys,
                    update_status=latest.get('state', 'Not checked') if manager != 'none' else 'Package manager missing',
                    update_progress=latest.get('progress'), latest_job=latest.get('id'), installed=True,
                    rebuild_available=definition_ready, operation_state=latest.get('state'),
                    operation_action=latest.get('action'),
                    last_checked=check.get('finished_at') or check.get('created_at'),
                    updates_available=check.get('updates_available')))
        types = {entry['name'].rsplit('-f', 1)[0] for entry in installed}
        fields = ('id', 'name', 'action', 'state', 'created_at', 'finished_at', 'progress')
        return dict(root=str(ROOT), installed=installed, staging=staging,
            jobs=[{key:entry[key] for key in fields if key in entry} for entry in reversed(history[-50:])],
            capabilities={'check': True, 'update': True, 'rebuild': True, 'delete': False, 'install': False},
            sources=self.sources(), catalog=[
                dict(id=name, title=title, description=description, installed=name in types,
                     key_packages=KEY_PACKAGES.get(name, []), supported_bases=['fedora', 'ubuntu'])
                for name,title,description in CATALOG],
            note='Temporary and retained directories are inspection-only. Redeploy requires a stored environment definition; deletion and direct catalog installation are not exposed by this worker.')
