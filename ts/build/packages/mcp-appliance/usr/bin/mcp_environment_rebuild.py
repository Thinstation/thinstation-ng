#!/usr/bin/python3
"""Build disposable distribution environments with signed, isolated sources."""
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
        mirrors=out.get('mirrors') or [{'url':out.get('url'),'keyring':out.get('keyring')}]
        if not isinstance(mirrors,list) or not mirrors:
            raise ValueError('APT source requires one or more mirrors')
        for mirror in mirrors:
            if not isinstance(mirror,dict) or not isinstance(mirror.get('url'),str) or not isinstance(mirror.get('keyring'),str):
                raise ValueError('Invalid APT mirror')
            if not mirror['url'].startswith('https://') or not (mirror['keyring'].startswith('/usr/share/keyrings/') or mirror['keyring'].startswith('/var/prstnt/mcp-appliance/config/keyrings/')):
                raise ValueError('Untrusted APT repository configuration')
        out['mirrors']=mirrors
        if not isinstance(out.get('suite'),str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,40}',out['suite']):
            raise ValueError('Invalid APT suite')
        script=out.get('bootstrap_script')
        if script is not None and (not isinstance(script,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,40}',script)):
            raise ValueError('Invalid bootstrap script')
    else:
        repo=out.get('repo_config')
        if repo is not None:
            approved=Path('/var/prstnt/mcp-appliance/config/dnf-repos')/name/release
            if not isinstance(repo,str) or Path(repo).parent!=approved or not repo.endswith('.repo'):
                raise ValueError('DNF repository file must be isolated by distro and release')
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
def rebuild(name, ident, log, options, create_only=False):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,62}',name):raise ValueError('Bad environment name')
    if not re.fullmatch(r'[a-f0-9]{32}',ident):raise ValueError('Invalid rebuild job identifier')
    file=MANIFEST/(name+'.json')
    data=json.loads(file.read_text())
    pkgs=data.get('packages')
    if not isinstance(pkgs,list) or not pkgs or len(pkgs)>200 or any(not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9_+][A-Za-z0-9_+.-]{0,99}',p) for p in pkgs):
        raise ValueError('Manifest must contain a validated package list')
    base=str(data.get('base','fedora')).lower()
    release=str(data.get('release','44'))
    source=resolve_source(base,release,data.get('source'))
    family=source['family']
    components=data.get('components') or source.get('components','main')
    if not isinstance(components,str) or not components.split() or any(c not in ('main','restricted','universe','multiverse') for c in components.split()):
        raise ValueError('Unsupported repository component selection')
    if create_only and ((ROOT/name).exists() or (ROOT/name).is_symlink()):
        raise ValueError('Creation target already exists')
    if family=='apt' and not Path('/usr/bin/debootstrap').exists():
        raise ValueError('Debian-family provisioning requires debootstrap')
    stage=ROOT/('.stage-'+ident)
    old=ROOT/('.previous-'+ident)
    target=ROOT/name
    if stage.exists() or old.exists() or target.is_symlink():raise ValueError('Unsafe environment path')
    if not ROOT.is_dir() or ROOT.is_symlink():raise ValueError('Unsafe environment root')
    if create_only:
        from mcp_environment_actions import rename_new
    stage.mkdir(mode=0o700)
    mounts=[]
    def mount_runtime():
        if mounts:return
        for rel,kind,src in [('dev','bind','/dev'),('dev/pts','bind','/dev/pts'),('proc','proc','proc'),('sys','sysfs','sysfs')]:
            dst=stage/rel
            dst.mkdir(parents=True,exist_ok=True)
            cmd=['mount','--bind',src,str(dst)] if kind=='bind' else ['mount','-t',kind,src,str(dst)]
            subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT)
            mounts.append(dst)
    def stop_staged_gpg_agents():
        import signal,time
        targets=[]
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():continue
            try:
                root=(proc/'root').resolve(strict=True)
                comm=(proc/'comm').read_text().strip()
                if root==stage.resolve() and comm in ('gpg-agent','scdaemon'):
                    targets.append(int(proc.name))
            except (OSError,RuntimeError):continue
        for pid in targets:
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass
        if targets:time.sleep(2)
    def unmount_runtime():
        import time
        while mounts:
            destination=mounts[-1]
            # Bind-mounted /dev can expose /dev/pts without a separate mount;
            # another chroot may already have released this mountpoint.
            if subprocess.run(['mountpoint','-q',str(destination)]).returncode!=0:
                mounts.pop()
                continue
            for attempt in range(10):
                result=subprocess.run(['umount',str(destination)],stdout=log,stderr=subprocess.STDOUT)
                if result.returncode==0:break
                time.sleep(1+attempt)
            else:
                raise RuntimeError('Chroot mount is still busy: '+str(destination))
            mounts.pop()
    try:
        if family=='apt':
            errors=[]
            for mirror in source['mirrors']:
                keyring=Path(mirror['keyring'])
                if not keyring.is_file():
                    errors.append('Missing trusted archive keyring: '+str(keyring))
                    continue
                if any(stage.iterdir()):
                    assert_inactive(stage)
                    shutil.rmtree(stage)
                    stage.mkdir(mode=0o700)
                cmd=['/usr/bin/debootstrap','--arch=amd64','--variant=minbase','--keyring='+str(keyring),
                     source['suite'],str(stage),mirror['url']]
                script=source.get('bootstrap_script')
                if script:
                    script_path=Path('/usr/share/debootstrap/scripts')/script
                    if not script_path.is_file():raise ValueError('Missing debootstrap compatibility script: '+script)
                    cmd.append(str(script_path))
                try:
                    log.write('Trying signed APT mirror: '+mirror['url']+'\n'); log.flush()
                    subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
                    dest=stage/'usr/share/keyrings'/keyring.name
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(keyring,dest)
                    # Carry appliance-trusted site CAs into the bootstrap root before
                    # APT connects to private mirrors over HTTPS. Keep public CA
                    # trust from the distribution's existing bundle.
                    anchors=Path('/etc/pki/ca-trust/source/anchors')
                    if anchors.is_dir():
                        ca_dest=stage/'usr/local/share/ca-certificates'
                        ca_dest.mkdir(parents=True,exist_ok=True)
                        bundle=stage/'etc/ssl/certs/ca-certificates.crt'
                        bundle.parent.mkdir(parents=True,exist_ok=True)
                        for ca in sorted(anchors.iterdir()):
                            if not ca.is_file() or ca.suffix.lower() not in ('.crt','.pem'):
                                continue
                            cert=ca.read_bytes()
                            if b'-----BEGIN CERTIFICATE-----' not in cert:
                                continue
                            (ca_dest/(ca.stem+'.crt')).write_bytes(cert)
                            with bundle.open('ab') as dst:
                                dst.write(bytes([10])+cert+bytes([10]))
                    sources=stage/'etc/apt/sources.list'
                    sources.write_text('deb [signed-by=/usr/share/keyrings/'+keyring.name+'] '+mirror['url']+' '+source['suite']+' '+components+'\n')
                    mount_runtime()
                    subprocess.run(['/usr/bin/chroot',str(stage),'/usr/bin/apt-get','update'],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=3600)
                    subprocess.run(['/usr/bin/chroot',str(stage),'/usr/bin/apt-get','-y','install']+pkgs,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
                    break
                except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
                    unmount_runtime()
                    errors.append(mirror['url']+': '+str(exc))
                    log.write('Mirror attempt failed; trying next configured mirror.\\n'); log.flush()
            else:
                raise RuntimeError('All signed APT mirrors failed: '+'; '.join(errors))
        else:
            pkgs=list(dict.fromkeys(pkgs+['gawk','dnf']))
            cmd=['/usr/bin/dnf','--installroot='+str(stage),'--releasever='+release,'-y','--setopt=install_weak_deps=False']
            if source.get('repo_config'):
                config=source.get('repo_config')
                if not config or not Path(config).is_file():raise ValueError('Missing approved DNF repo config')
                cmd+=['--setopt=reposdir='+str(Path(config).parent)]
            else:
                cmd+=['--use-host-config']
            subprocess.run(cmd+options+['install']+pkgs,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
        # A staged chroot cannot use the host's loopback DNS stub.
        resolver=Path('/run/systemd/resolve/resolv.conf')
        if not resolver.is_file():resolver=Path('/etc/resolv.conf')
        (stage/'etc').mkdir(parents=True,exist_ok=True)
        shutil.copyfile(resolver,stage/'etc/resolv.conf')
        if family=='dnf':
            repo_source=source.get('repo_config')
            if repo_source:
                repo_dir=stage/'etc/yum.repos.d'
                repo_dir.mkdir(parents=True,exist_ok=True)
                for repo_file in Path(repo_source).parent.glob('*.repo'):
                    shutil.copy2(repo_file,repo_dir/repo_file.name)
                for keyfile in Path('/var/prstnt/mcp-appliance/config/dnf-repos').glob('*.gpg'):
                    destination=stage/keyfile.as_posix().lstrip('/')
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(keyfile,destination)
        if family=='dnf':
            anchors=Path('/etc/pki/ca-trust/source/anchors')
            dest=stage/'etc/pki/ca-trust/source/anchors'
            dest.mkdir(parents=True,exist_ok=True)
            if anchors.is_dir():
                for ca in anchors.iterdir():
                    if ca.is_file() and ca.suffix.lower() in ('.crt','.pem'):
                        shutil.copy2(ca,dest/ca.name)
            # Prevent distribution-provided mirrorlists from superseding
            # the explicitly approved repository configuration.
            if source.get('repo_config'):
                repos=stage/'etc/yum.repos.d'
                approved={p.name for p in Path(source['repo_config']).parent.glob('*.repo')}
                for repo in repos.glob('*.repo'):
                    if repo.name not in approved:repo.rename(repo.with_suffix('.repo.disabled'))
            subprocess.run(['/usr/bin/chroot',str(stage),'/usr/bin/update-ca-trust','extract'],
                           check=True,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        mount_runtime()
        if data.get('thinstation_init', True):
            import hashlib, urllib.request
            expected='cf15984d5db95b17d75a1ce7c43edea5b00a38b1cecc56309f3107f7a3260c82'
            with urllib.request.urlopen('https://distro.thinstation.org/init.sh', timeout=60) as response:
                payload=response.read(1048577)
            if len(payload)>1048576 or hashlib.sha256(payload).hexdigest()!=expected:
                raise ValueError('ThinStation initializer hash verification failed')
            script=stage/'tmp/thinstation-init.sh'
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_bytes(payload)
            subprocess.run(['/usr/bin/chroot', str(stage), '/usr/bin/env', '-i',
                            'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                            'HOME=/root', '/usr/bin/bash', '/tmp/thinstation-init.sh'],
                           check=True, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
            script.unlink()
        if not (stage/'etc/os-release').is_file() or not (stage/('usr/bin/rpm' if family=='dnf' else 'usr/bin/apt-get')).exists():raise ValueError('Staged root failed validation')
        for entry in data.get('required_paths',[]):
            if not isinstance(entry,str) or not entry.startswith('/usr/') or '..' in Path(entry).parts:raise ValueError('Invalid required path')
            required=stage/entry.lstrip('/')
            if not required.exists() or not required.resolve().is_relative_to(stage.resolve()):raise ValueError('Missing or unsafe required path: '+entry)
        stop_staged_gpg_agents()
        unmount_runtime()
        assert_inactive(target)
        if create_only:
            rename_new(stage,target)
            log.write('New environment activated without replacing an existing root.\n');log.flush()
            return None
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
        stop_staged_gpg_agents()
        unmount_runtime()
        if stage.exists():
            # Cleanup is allowed only after mounts and process references are gone.
            assert_inactive(stage)
            shutil.rmtree(stage)
if __name__=='__main__':sys.exit(2)
