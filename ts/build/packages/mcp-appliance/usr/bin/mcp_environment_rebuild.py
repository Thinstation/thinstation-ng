#!/usr/bin/python3
"""Build disposable Fedora environment in staging, validate, then replace."""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
ROOT=Path('/var/prstnt/mcp-appliance/chroots')
MANIFEST=Path('/var/prstnt/mcp-appliance/config/environment-manifests')
def rebuild(name, ident, log, options):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',name):raise ValueError('Bad environment name')
    file=MANIFEST/(name+'.json')
    data=json.loads(file.read_text())
    pkgs=data.get('packages')
    if not isinstance(pkgs,list) or not pkgs or len(pkgs)>200 or any(not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9_+.-]{1,100}',p) for p in pkgs):
        raise ValueError('Manifest must contain a validated package list')
    release=str(data.get('release','44'))
    if not re.fullmatch(r'[0-9]{1,3}',release):raise ValueError('Invalid release')
    stage=ROOT/('.stage-'+ident)
    old=ROOT/('.previous-'+ident)
    target=ROOT/name
    if stage.exists() or old.exists() or target.is_symlink():raise ValueError('Unsafe environment path')
    stage.mkdir(mode=0o700)
    try:
        cmd=['/usr/bin/dnf','--installroot='+str(stage),'--releasever='+release,'-y','--setopt=install_weak_deps=False']+options+['install']+pkgs
        subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
        if not (stage/'etc/os-release').is_file() or not (stage/'usr/bin/rpm').exists():raise ValueError('Staged root failed validation')
        for entry in data.get('required_paths',[]):
            if not isinstance(entry,str) or not entry.startswith('/usr/') or '..' in Path(entry).parts:raise ValueError('Invalid required path')
            if not (stage/entry.lstrip('/')).exists():raise ValueError('Missing required path: '+entry)
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
