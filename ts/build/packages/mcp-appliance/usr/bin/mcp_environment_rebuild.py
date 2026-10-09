#!/usr/bin/python3
"""Build disposable Fedora environment in staging, validate, then replace."""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
ROOT=Path('/var/prstnt/mcp-appliance/chroots')
MANIFEST=Path('/var/prstnt/mcp-appliance/config/environment-manifests')
SOURCE_DIR=Path('/usr/share/mcp-appliance/distro-sources')
OVERRIDE_DIR=Path('/var/prstnt/mcp-appliance/config/distro-sources')
def resolve_source(base, release, source_name=None):
    name=str(source_name or base)
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',name):raise ValueError('Invalid source name')
    if not re.fullmatch(r'[A-Za-z0-9.]{1,16}',release):raise ValueError('Invalid release')
    path=OVERRIDE_DIR/(name+'.json')
    if not path.exists():path=SOURCE_DIR/(name+'.json')
    if not path.is_file():raise ValueError('Unknown distro source: '+name)
    config=json.loads(path.read_text())
    if config.get('family') not in ('apt','dnf'):raise ValueError('Invalid distro source family')
    entry=config.get('releases',{}).get(release)
    if not isinstance(entry,dict):raise ValueError('Unsupported release for '+name+': '+release)
    out=dict(entry,family=config['family'])
    if out['family']=='apt':
        if not all(isinstance(out.get(x),str) for x in ('url','suite','keyring')):
            raise ValueError('Incomplete APT source')
        if not out['url'].startswith('https://') or not out['keyring'].startswith('/usr/share/keyrings/'):
            raise ValueError('Untrusted APT repository configuration')
    else:
        if 'repo_config' in out and not str(out['repo_config']).startswith('/var/prstnt/mcp-appliance/config/dnf-repos/'):
            raise ValueError('DNF repository configs must be under persistent dnf-repos')
    return out
def assert_inactive(target):
    """Refuse replacement while target contains mounts or referenced process paths."""
    if not target.exists(): return
    resolved=target.resolve()
    def beneath(path):
        try: return path==resolved or resolved in path.parents
        except (OSError,RuntimeError): return False
    try:
        mounts=Path('/proc/self/mountinfo').read_text().splitlines()
    except OSError as exc:
        raise RuntimeError('Unable to inspect mounts') from exc
    for line in mounts:
        parts=line.split()
        if len(parts)>4:
            mount=Path(parts[4].replace('\\040',' '))
            if beneath(mount): raise RuntimeError('Environment contains active mounts')
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        for entry in ('cwd','root','exe'):
            try: linked=(proc/entry).resolve(strict=True)
            except (OSError,RuntimeError):continue
            if beneath(linked):raise RuntimeError('Environment is referenced by a running process')
def rebuild(name, ident, log, options):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',name):raise ValueError('Bad environment name')
    if not re.fullmatch(r'[a-f0-9]{32}',ident):raise ValueError('Invalid rebuild job identifier')
    file=MANIFEST/(name+'.json')
    data=json.loads(file.read_text())
    pkgs=data.get('packages')
    if not isinstance(pkgs,list) or not pkgs or len(pkgs)>200 or any(not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9_+.-]{1,100}',p) for p in pkgs):
        raise ValueError('Manifest must contain a validated package list')
    base=str(data.get('base','fedora')).lower()
    release=str(data.get('release','44'))
    source=resolve_source(base,release,data.get('source'))
    family=source['family']
    if family=='apt' and not Path('/usr/bin/debootstrap').exists():
        raise ValueError('Debian-family provisioning requires debootstrap')
    stage=ROOT/('.stage-'+ident)
    old=ROOT/('.previous-'+ident)
    target=ROOT/name
    if stage.exists() or old.exists() or target.is_symlink():raise ValueError('Unsafe environment path')
    if not ROOT.is_dir() or ROOT.is_symlink():raise ValueError('Unsafe environment root')
    stage.mkdir(mode=0o700)
    try:
        if family=='apt':
            keyring=Path(source['keyring'])
            if not keyring.is_file():raise ValueError('Missing trusted archive keyring: '+str(keyring))
            cmd=['/usr/bin/debootstrap','--arch=amd64','--variant=minbase','--keyring='+str(keyring),
                 source['suite'],str(stage),source['url']]
            subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
            # Ensure initial and subsequent package transactions use the same source trust anchor.
            dest=stage/'usr/share/keyrings'/keyring.name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(keyring,dest)
            sources=stage/'etc/apt/sources.list'
            sources.write_text('deb [signed-by=/usr/share/keyrings/'+keyring.name+'] '+source['url']+' '+source['suite']+' '+source.get('components','main')+'\\n')
            subprocess.run(['/usr/bin/chroot',str(stage),'/usr/bin/apt-get','update'],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=3600)
            subprocess.run(['/usr/bin/chroot',str(stage),'/usr/bin/apt-get','-y','install']+pkgs,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
        else:
            cmd=['/usr/bin/dnf','--installroot='+str(stage),'--releasever='+release,'-y','--setopt=install_weak_deps=False']
            if source.get('repo_config'):
                config=source.get('repo_config')
                if not config or not Path(config).is_file():raise ValueError('Missing approved DNF repo config')
                cmd+=['--setopt=reposdir='+str(Path(config).parent)]
            subprocess.run(cmd+options+['install']+pkgs,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
        if not (stage/'etc/os-release').is_file() or not (stage/('usr/bin/rpm' if family=='dnf' else 'usr/bin/apt-get')).exists():raise ValueError('Staged root failed validation')
        for entry in data.get('required_paths',[]):
            if not isinstance(entry,str) or not entry.startswith('/usr/') or '..' in Path(entry).parts:raise ValueError('Invalid required path')
            required=stage/entry.lstrip('/')
            if not required.exists() or not required.resolve().is_relative_to(stage.resolve()):raise ValueError('Missing or unsafe required path: '+entry)
        assert_inactive(target)
        had_target=target.is_dir()
        if had_target:os.rename(target,old)
        try:os.rename(stage,target)
        except Exception:
            if had_target:os.rename(old,target)
            raise
        log.write('Activation complete; previous environment retained at '+str(old) if had_target else 'Activation complete')
        log.flush()
        return str(old) if had_target else None
    finally:
        if stage.exists():shutil.rmtree(stage)
if __name__=='__main__':sys.exit(2)
