#!/usr/bin/python3
"""Inventory and authenticated job scheduling for persistent environments."""
from pathlib import Path
from datetime import datetime, timezone
import os
import json
import uuid
import subprocess
import re

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
        if not isinstance(saved,dict):saved={}
        try: lines=Path('/etc/thinstation.defaults').read_text().splitlines()
        except OSError: lines=[]
        def default(key):
            return next((x.partition('=')[2].strip().strip('"') for x in lines if x.startswith(key+'=')),'')
        return {'fedora_url':saved.get('fedora_url',default('MCP_PACKAGE_FEDORA_URL')),'updates_url':saved.get('updates_url',default('MCP_PACKAGE_UPDATES_URL')),'fallback':False,'fallback_supported':False,'source':'persistent' if saved else 'build defaults'}

    def save_sources(self, body):
        from urllib.parse import urlsplit
        from mcp_environment_actions import atomic_json
        result={}
        for key in ('fedora_url','updates_url'):
            val=str(body.get(key,'')).strip()
            if len(val)>1024:raise ValueError('Repository URL too long')
            if val:
                url=urlsplit(val)
                if url.scheme!='https' or not url.hostname or url.username or url.password or url.fragment:raise ValueError('Repository URL must be HTTPS without credentials or fragments')
            result[key]=val
        if body.get('fallback'):raise ValueError('Automatic fallback is not yet supported')
        atomic_json('/var/prstnt/mcp-appliance/config/package-sources.json',result)
        return self.sources()

    def plan_create(self, body):
        from mcp_environment_actions import create_plan
        return create_plan(body,ROOT,MANIFESTS)

    def start(self, body, owner):
        from mcp_environment_actions import start_operation
        return start_operation(self,body,owner,ROOT,STATE,MANIFESTS)

    def _schedule(self,name,action,owner,state,extra=None):
        from mcp_environment_actions import atomic_json
        ident=uuid.uuid4().hex
        job={'id':ident,'name':name,'action':action,'state':'queued','owner':owner,'created_at':datetime.now(timezone.utc).isoformat()}
        job.update(extra or {})
        atomic_json(state/(ident+'.json'),job)
        try:
            subprocess.run(['/usr/bin/systemd-run','--unit=mcp-env-'+ident,'--collect',
                            '--property=PrivateMounts=yes','--property=KillMode=control-group',
                            '/usr/bin/python3','/usr/bin/mcp-environment-worker',ident],
                           check=True,timeout=15,capture_output=True)
        except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired):
            job.update(state='failed',finished_at=datetime.now(timezone.utc).isoformat(),
                       error='Environment worker could not start',exit_code=1)
            atomic_json(state/(ident+'.json'),job)
            raise ValueError('Environment worker could not start')
        return {key:value for key,value in job.items() if key not in ('owner','manifest','plan_token','target_token','confirmation')}

    def job(self, ident):
        if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid job ID')
        file=STATE/(ident+'.json')
        if file.is_symlink() or not file.is_file():raise ValueError('Job missing')
        job=json.loads(file.read_text())
        for key in ('owner','manifest','plan_token','target_token','confirmation'):job.pop(key,None)
        log=STATE/(ident+'.log')
        if log.is_file() and not log.is_symlink():
            with log.open('rb') as stream:
                stream.seek(max(0,log.stat().st_size-12000))
                job['log_tail']=stream.read().decode(errors='replace')
        else:job['log_tail']=''
        return job

    def status(self):
        from mcp_environment_actions import delete_metadata,catalog_recipes
        known={name:(title,desc) for name,title,desc in CATALOG}
        history=[]
        for jobfile in STATE.glob('*.json'):
            if jobfile.is_symlink():continue
            try:entry=json.loads(jobfile.read_text())
            except (OSError,ValueError):continue
            if not isinstance(entry,dict) or not re.fullmatch(r'[a-f0-9]{32}',str(entry.get('id',''))):continue
            history.append(entry)
        history.sort(key=lambda entry:str(entry.get('created_at','')))
        by_id={entry['id']:entry for entry in history}
        by_name={}
        for entry in history:by_name.setdefault(str(entry.get('name','')),[]).append(entry)
        installed,staging=[],[]
        if ROOT.is_dir():
            for path in sorted(ROOT.iterdir()):
                if path.is_symlink() or not path.is_dir():continue
                name=path.name
                if name.startswith('.'):
                    kind='previous' if name.startswith('.previous-') else 'stage' if name.startswith('.stage-') else 'deleting' if name.startswith('.deleting-') else 'internal'
                    previous=by_id.get(name.partition('-')[2],{})
                    try:modified=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()
                    except OSError:modified=None
                    staging.append(dict(name=name,kind=kind,state=previous.get('state'),
                        environment=previous.get('name'),latest_job=previous.get('id'),modified_at=modified,
                        **delete_metadata(ROOT,name,STATE)))
                    continue
                dnf=(path/'usr/bin/dnf').exists() or (path/'usr/bin/dnf5').exists()
                apt=(path/'usr/bin/apt-get').exists()
                manager='dnf' if dnf else 'apt' if apt else 'none'
                manifest_file=MANIFESTS/(name+'.json')
                try:manifest=json.loads(manifest_file.read_text()) if not manifest_file.is_symlink() else {}
                except (OSError,ValueError):manifest={}
                if not isinstance(manifest,dict):manifest={}
                kind=manifest.get('profile',name.rsplit('-f',1)[0])
                title,description=known.get(kind,(name,'Custom persistent execution environment'))
                packages=manifest.get('packages',[])
                definition_ready=bool(isinstance(packages,list) and 0<len(packages)<=200
                    and all(isinstance(item,str) and re.fullmatch(r'[A-Za-z0-9_+][A-Za-z0-9_+.-]{0,99}',item) for item in packages)
                    and re.fullmatch(r'[a-z][a-z0-9-]{0,62}',name))
                keys=manifest.get('key_packages',KEY_PACKAGES.get(kind,[]))
                keys=[item for item in keys if isinstance(item,str)] if isinstance(keys,list) else []
                release='Unknown'
                try:
                    text=(path/'etc/os-release').read_text(errors='replace')
                    release=next((line.split('=',1)[1].strip().strip('"') for line in text.splitlines() if line.startswith('PRETTY_NAME=')),release)
                except OSError:pass
                records=by_name.get(name,[])
                latest=records[-1] if records else {}
                observations=[entry for entry in records if entry.get('action')=='check' or entry.get('checked_at') or entry.get('check_state')]
                check=observations[-1] if observations else {}
                if check and any(entry.get('action') in ('update','rebuild','install','delete')
                                 and str(entry.get('created_at',''))>str(check.get('created_at','')) for entry in records):check={}
                successful=check.get('state') in ('completed','succeeded') and check.get('check_state')!='failed'
                check_time=(check.get('checked_at') or check.get('finished_at') or check.get('created_at')) if successful else None
                check_failed=check.get('check_state')=='failed' or check.get('state')=='failed'
                installed.append(dict(name=name,title=title,description=description,os=release,profile=kind,
                    dnf_available=dnf,apt_available=apt,package_manager=manager,key_packages=keys,
                    update_status=latest.get('state','Not checked') if manager!='none' else 'Package manager missing',
                    update_progress=latest.get('progress'),latest_job=latest.get('id'),installed=True,
                    rebuild_available=definition_ready,operation_state=latest.get('state'),operation_action=latest.get('action'),
                    last_checked=check_time,last_check_attempt=check.get('check_attempted_at') or check.get('checked_at') or check.get('created_at'),
                    last_check_job=check.get('id'),check_state='failed' if check_failed else 'succeeded' if successful else check.get('state'),
                    updates_available=check.get('updates_available') if successful else None,
                    update_count=check.get('update_count') if successful else None,held_count=check.get('held_count') if successful else None,
                    **delete_metadata(ROOT,name,STATE)))
        existing={entry['name'] for entry in installed}
        for name,records in by_name.items():
            latest=records[-1]
            if name not in existing and latest.get('action') in ('install','rebuild') and latest.get('state') in ('queued','running'):
                installed.append(dict(name=name,title=name,description='Provisioning a new environment',os='Pending',
                    package_manager='none',key_packages=[],installed=False,operation_state=latest['state'],
                    operation_action=latest['action'],latest_job=latest['id'],rebuild_available=False,
                    delete_available=False,update_status=latest['state']))
        types={entry.get('profile',entry['name'].rsplit('-f',1)[0]) for entry in installed}
        recipes=catalog_recipes()
        fields=('id','name','action','state','created_at','started_at','finished_at','progress','checked_at','check_state','updates_available','update_count','held_count')
        return dict(root=str(ROOT),installed=installed,staging=staging,
            jobs=[{key:entry[key] for key in fields if key in entry} for entry in reversed(history[-50:])],
            capabilities={'check':True,'update':True,'rebuild':True,'delete':True,'install':True},
            sources=self.sources(),catalog=[dict(id=name,title=title,description=description,installed=name in types,
                key_packages=KEY_PACKAGES.get(name,[]),supported_bases=[option['id'] for option in recipes[name]['bases']],
                install_available=bool(recipes[name]['bases']),**recipes[name]) for name,title,description in CATALOG],
            note='Deletion requires target confirmation and refuses active use. Catalog installation creates a new named root from configured signed repositories.')
