#!/usr/bin/python3
"""Guarded environment lifecycle and distribution-native package jobs."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time

ACTIVE = {'queued', 'running'}
NAME = re.compile(r'[a-z][a-z0-9-]{0,62}')
INTERNAL = re.compile(r'\.(?:stage|previous|deleting)-[a-f0-9]{32}')
COMMON = {
 'fedora': ['bash','coreutils','ca-certificates','curl','openssl','gnupg2','dnf'],
 'ubuntu': ['bash','coreutils','ca-certificates','curl','openssl','gnupg','apt'],
}
# These are package recipes, not display-only tool names. Never execute a
# downloaded shell installer or silently add an unsigned third-party source.
PROFILES = {
 'ai': {'fedora':['python3','python3-pip','git','cmake','gcc-c++'], 'ubuntu':['python3','python3-pip','python3-venv','git','cmake','build-essential'],
        'note':'Python and native-build foundation. Model engines, weights and Python applications are installed separately.'},
 'avatar': {'fedora':['blender','python3','ffmpeg-free'], 'ubuntu':['blender','python3','ffmpeg']},
 'browser': {'fedora':['chromium','firefox','python3','python3-pip'],
             'note':'Native browsers on Fedora. Ubuntu snap-based browser packages are not suitable for these chroots. Playwright is a separate Python installation.'},
 'cad': {'fedora':['freecad','blender','meshlab'], 'ubuntu':['freecad','blender','meshlab']},
 'cuda': {'ubuntu':['nvidia-cuda-toolkit','python3'],
          'note':'Ubuntu distribution CUDA toolkit; requires multiverse in the configured mirror. Uses the appliance GPU driver; does not replace it.'},
 'media': {'fedora':['ffmpeg-free','mediainfo'], 'ubuntu':['ffmpeg','mediainfo']},
 'photo': {'fedora':['ImageMagick','perl-Image-ExifTool','darktable'], 'ubuntu':['imagemagick','libimage-exiftool-perl','darktable']},
 'wireshark': {'fedora':['wireshark-cli','tcpdump'], 'ubuntu':['tshark','tcpdump']},
}


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else (default or {})
    except (OSError, ValueError):
        return default or {}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.'+path.name+'.'+str(os.getpid())+'.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def lock(path, nonblocking=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        except BlockingIOError as exc:
            raise ValueError('An operation is already active for this environment') from exc
        yield


def target_path(root, name, internal=False, missing=False):
    root = Path(root)
    if not (NAME.fullmatch(name) or (internal and INTERNAL.fullmatch(name))):
        raise ValueError('Invalid environment name')
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Unsafe environment root')
    target = root / name
    if target.is_symlink():
        raise ValueError('Symbolic-link environment roots are not permitted')
    if target.exists() and not target.is_dir():
        raise ValueError('Environment root is not a directory')
    if not missing and not target.is_dir():
        raise ValueError('Environment no longer exists; refresh the inventory')
    if target.resolve().parent != root.resolve():
        raise ValueError('Environment path escapes the managed root')
    return target


def fingerprint(target):
    info = target.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('Environment is not a real directory')
    return hashlib.sha256(f'{info.st_dev}:{info.st_ino}:{info.st_ctime_ns}'.encode()).hexdigest()


def within(path, target):
    text = str(path).removesuffix(' (deleted)')
    return text == str(target) or text.startswith(str(target)+'/')


def decode_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1],8)), value)


def assert_unused(target, proc=Path('/proc')):
    """Fail closed on mounts, processes, open descriptors and mapped files."""
    target = target.resolve(strict=True)
    try:
        mounts = (proc/'self/mountinfo').read_text()
    except OSError as exc:
        raise ValueError('Cannot verify mount safety') from exc
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts)>4 and within(decode_mount(parts[4]),target):
            raise ValueError('Environment has active mounts; stop its workload and unmount it first')
    mount_namespaces=set()
    for process in proc.iterdir():
        if not process.name.isdigit() or int(process.name)==os.getpid():
            continue
        try:
            namespace=os.readlink(process/'ns/mnt')
            if namespace not in mount_namespaces:
                other_mounts=(process/'mountinfo').read_text()
                mount_namespaces.add(namespace)
                for line in other_mounts.splitlines():
                    parts=line.split()
                    if len(parts)>4 and within(decode_mount(parts[4]),target):
                        raise ValueError('Environment has an active mount in process namespace '+process.name)
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise ValueError('Cannot verify mount-namespace safety') from exc
        for entry in ('root','cwd','exe'):
            try:
                linked = os.readlink(process/entry)
            except FileNotFoundError:
                continue
            except PermissionError as exc:
                raise ValueError('Cannot verify process safety') from exc
            except OSError as exc:
                raise ValueError('Cannot inspect process references') from exc
            if within(linked,target):
                raise ValueError('Environment is in use by process '+process.name)
        try:
            for descriptor in (process/'fd').iterdir():
                try:
                    if within(os.readlink(descriptor),target):
                        raise ValueError('Environment has an open file in process '+process.name)
                except FileNotFoundError:
                    pass
                except PermissionError as exc:
                    raise ValueError('Cannot verify open-file safety') from exc
                except OSError:
                    continue
            maps = (process/'maps').read_text(errors='replace')
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise ValueError('Cannot verify open-file safety') from exc
        for line in maps.splitlines():
            parts=line.split(None,5)
            if len(parts)==6 and within(parts[5],target):
                raise ValueError('Environment has a mapped file in process '+process.name)


def busy_job(state, name, exclude=None):
    stage_id = name.partition('-')[2] if INTERNAL.fullmatch(name) else None
    for path in Path(state).glob('*.json'):
        if path.is_symlink():continue
        value=read_json(path)
        if value.get('id')==exclude or value.get('state') not in ACTIVE:
            continue
        if value.get('name')==name or (stage_id and value.get('id')==stage_id):
            return value
    return None


def delete_metadata(root, name, state):
    try:
        target=target_path(root,name,internal=True)
        token=fingerprint(target)
        if busy_job(state,name):
            return {'delete_available':False,'delete_token':token,'delete_reason':'An operation is still active.'}
        # Full process/open-file checks are repeated by the worker immediately
        # before deletion. A visible action is not a promise a root is idle.
        mounts=Path('/proc/self/mountinfo').read_text()
        if any(len(p:=line.split())>4 and within(decode_mount(p[4]),target.resolve()) for line in mounts.splitlines()):
            return {'delete_available':False,'delete_token':token,'delete_reason':'Active mounts; stop and unmount this environment first.'}
        return {'delete_available':True,'delete_token':token,'delete_reason':'Delete after confirming; active use is checked again by the worker.'}
    except (OSError,ValueError):
        return {'delete_available':False,'delete_reason':'Unsupported, missing or unsafe directory.'}


def source_choices(base):
    from mcp_environment_rebuild import SOURCE_DIR, OVERRIDE_DIR, resolve_source
    source=Path(OVERRIDE_DIR)/(base+'.json')
    if not source.is_file():source=Path(SOURCE_DIR)/(base+'.json')
    choices=[]
    configured=read_json(source).get('releases',{})
    if not isinstance(configured,dict):return []
    for release in configured:
        try:
            definition=resolve_source(base,str(release))
            if definition['family']=='apt':
                if not Path('/usr/bin/debootstrap').is_file():continue
                if not any(Path(m['keyring']).is_file() for m in definition.get('mirrors',[])):continue
            elif not Path('/usr/bin/dnf').exists():continue
            if definition.get('repo_config') and not Path(definition['repo_config']).is_file():continue
            choices.append(str(release))
        except (OSError,ValueError):
            continue
    return sorted(choices)


def catalog_recipes():
    releases={base:source_choices(base) for base in COMMON}
    return {key:{'bases':[{'id':base,'releases':releases[base],
                          'packages':list(dict.fromkeys(COMMON[base]+recipe[base])),
                          'components':'main restricted universe multiverse' if base=='ubuntu' else None}
                         for base in COMMON if base in recipe and releases[base]],
                 'install_note':recipe.get('note','Only packages from configured, signed distribution repositories are installed.')}
            for key,recipe in PROFILES.items()}


def create_plan(body, root, manifests):
    name=str(body.get('name',''))
    target=target_path(root,name,missing=True)
    if target.exists() or (Path(manifests)/(name+'.json')).exists() or (Path(manifests)/(name+'.json')).is_symlink():
        raise ValueError('That name already exists or has a stored definition; choose a different name')
    profile=str(body.get('profile',''))
    base=str(body.get('base',''))
    release=str(body.get('release',''))
    recipe=catalog_recipes().get(profile,{})
    option=next((item for item in recipe.get('bases',[]) if item['id']==base and release in item['releases']),None)
    if not option:raise ValueError('The selected profile/base/release is not provisionable with the configured sources')
    from mcp_environment_rebuild import resolve_source
    source_definition=resolve_source(base,release,base)
    source_digest=hashlib.sha256(json.dumps(source_definition,sort_keys=True).encode()).hexdigest()
    manifest={'schema':1,'profile':profile,'base':base,'source':base,'release':release,
              'packages':option['packages'],'key_packages':PROFILES[profile][base],
              'components':option['components'],'thinstation_init':False,
              'source_digest':source_digest}
    # This recipe is complete without an unpinned post-install network script.
    # Site certificates are still copied by the existing provisioning worker.
    payload={'name':name,'manifest':manifest}
    token=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    return {**payload,'plan_token':token,'confirmation':'CREATE '+name,
            'note':recipe['install_note'],
            'warning':'Creates a new disposable root. Existing environments are never replaced. Package availability depends on the configured signed repositories.'}


def start_operation(api, body, owner, root, state, manifests):
    name=str(body.get('name',''))
    action=str(body.get('action',''))
    if action not in ('check','update','rebuild','install','delete'):
        raise ValueError('Unsupported environment action')
    target=target_path(root,name,internal=action=='delete',missing=action in ('rebuild','install'))
    with lock(Path(state)/'.lock'):
        if busy_job(state,name):raise ValueError('An operation is already active for this environment')
        extra={}
        if action=='install':
            plan=create_plan(body,root,manifests)
            if body.get('confirmation')!=plan['confirmation'] or body.get('plan_token')!=plan['plan_token']:
                raise ValueError('Review the current creation plan before confirming')
            extra={'manifest':plan['manifest'],'plan_token':plan['plan_token']}
        elif action=='delete':
            if body.get('confirmation')!='DELETE '+name or body.get('delete_token')!=fingerprint(target):
                raise ValueError('Deletion confirmation is missing or stale; refresh and review the target again')
            assert_unused(target)
            extra={'target_token':body['delete_token'],'confirmation':body['confirmation']}
        else:
            if action=='rebuild' and not (Path(manifests)/(name+'.json')).is_file():
                raise ValueError('No approved environment manifest; redeploy blocked')
            if action in ('update','rebuild') and target.exists():assert_unused(target)
        return api._schedule(name,action,owner,Path(state),extra=extra)


def delete_root(job, root, state, manifests, log):
    target=target_path(root,job['name'],internal=True)
    if job.get('confirmation')!='DELETE '+job['name'] or fingerprint(target)!=job.get('target_token'):
        raise ValueError('The deletion target changed since confirmation; refresh before retrying')
    if busy_job(state,job['name'],exclude=job['id']):raise ValueError('A matching operation is active')
    assert_unused(target)
    definition=Path(manifests)/(job['name']+'.json') if NAME.fullmatch(job['name']) else None
    if definition is not None and definition.is_symlink():raise ValueError('Refusing symbolic-link definition')
    if not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError('Safe directory deletion is unavailable on this Python platform')
    if not re.fullmatch('[a-f0-9]{32}',job['id']):raise ValueError('Invalid job identifier')
    hold=Path(root)/('.deleting-'+job['id'])
    if hold.exists() or hold.is_symlink():raise ValueError('Deletion staging name already exists')
    if fingerprint(target)!=job.get('target_token'):
        raise ValueError('Deletion target changed while safety checks ran')
    identity=target.lstat()
    rename_new(target,hold)
    try:
        renamed=hold.lstat()
        if not stat.S_ISDIR(renamed.st_mode) or (renamed.st_dev,renamed.st_ino)!=(identity.st_dev,identity.st_ino):
            raise ValueError('Deletion target changed during quarantine')
        assert_unused(hold)
    except Exception:
        if not target.exists():os.rename(hold,target)
        raise
    # Only the confirmed root is removed. shutil's fd-based traversal does not
    # follow child symlinks. Mounted roots and external processes are refused.
    shutil.rmtree(hold)
    if NAME.fullmatch(job['name']):
        definition=Path(manifests)/(job['name']+'.json')
        if definition.is_symlink():raise ValueError('Refusing symbolic-link definition')
        if definition.is_file():
            archive=Path(state)/'deleted-definitions'/(job['id']+'.json')
            archive.parent.mkdir(parents=True,exist_ok=True)
            rename_new(definition,archive)
    log.write('Deleted only the confirmed environment directory. Stored definition archived; external paths were not removed.\n')


def distro_info(root):
    data={}
    for line in (Path(root)/'etc/os-release').read_text().splitlines():
        key,separator,value=line.partition('=')
        if separator:data[key]=value.strip().strip('\"\'')
    release=data.get('VERSION_ID','')
    if not re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,3}){0,2}',release):
        raise ValueError('Unsupported or missing distribution version: '+release)
    manager='apt' if (Path(root)/'usr/bin/apt-get').exists() else 'dnf' if any((Path(root)/p).exists() for p in ('usr/bin/dnf','usr/bin/dnf5')) else None
    if not manager:raise ValueError('No supported package manager is installed')
    return data.get('ID',''),release,manager


def apt_result(output):
    match=re.search(r'(?m)^([0-9]+) upgraded, ([0-9]+) newly installed, ([0-9]+) to remove and ([0-9]+) not upgraded\.',output)
    if not match:raise ValueError('APT did not return a recognizable upgrade summary; inspect the log')
    upgrades,added,removed,held=map(int,match.groups())
    return {'updates_available':bool(upgrades or added or held),'update_count':upgrades+added,'held_count':held}


def package_prefix(root,manager,options=()):
    tool='/usr/bin/apt-get' if manager=='apt' else '/usr/bin/dnf' if (Path(root)/'usr/bin/dnf').exists() else '/usr/bin/dnf5'
    return ['/usr/bin/chroot',str(root),'/usr/bin/env','-i',
            'PATH=/usr/sbin:/usr/bin:/sbin:/bin','HOME=/root','LANG=C','LC_ALL=C',
            'DEBIAN_FRONTEND=noninteractive',tool,*options]


def run_command(command,log,timeout=1800,allowed=(0,)):
    offset=log.tell()
    log.write('$ '+ ' '.join(command)+'\n');log.flush()
    process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:rc=process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        import signal
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
        raise ValueError('Package operation timed out')
    log.flush()
    with open(log.name,errors='replace') as stream:
        stream.seek(offset)
        output=stream.read(8*1024*1024+1)
    if rc not in allowed:raise ValueError('Package command failed (exit '+str(rc)+'). '+output[-1600:])
    if len(output)>8*1024*1024:raise ValueError('Package output exceeds status parser limit; see full log')
    return rc,output


def package_operation(target,action,log,save,sources):
    base,release,manager=distro_info(target)
    options=[]
    if manager=='dnf':
        options=['--setopt=skip_if_unavailable=False']
        if base=='fedora':
            from urllib.parse import urlsplit
            for key,repo in (('fedora_url','fedora'),('updates_url','updates')):
                url=sources.get(key,'')
                if not url:continue
                parsed=urlsplit(url)
                if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                    raise ValueError('Invalid Fedora mirror override')
                url=url.replace('$releasever',release).replace('$basearch','x86_64')
                options += ['--setopt='+repo+'.metalink=','--setopt='+repo+'.mirrorlist=','--setopt='+repo+'.baseurl='+url]
    prefix=package_prefix(target,manager,options)
    save(package_source=base+' '+release+' / environment repositories',progress=10)
    if manager=='apt':
        run_command(prefix+['-o','APT::Update::Error-Mode=any','update'],log)
    if action=='update':
        save(progress=35)
        command=prefix+(['-y','--no-remove','-o','Dpkg::Options::=--force-confdef','-o','Dpkg::Options::=--force-confold','upgrade'] if manager=='apt' else ['--refresh','-y','upgrade'])
        run_command(command,log,timeout=7200)
        save(packages_updated_at=now())
    save(progress=85)
    if manager=='apt':
        rc,output=run_command(prefix+['-s','upgrade'],log)
        result=apt_result(output)
    else:
        rc,output=run_command(prefix+['--refresh','check-upgrade' if base=='fedora' else 'check-update'],log,allowed=(0,100))
        rows=re.findall(r'(?m)^\S+\.(?:x86_64|aarch64|noarch|i686)\s+\S+\s+\S+',output)
        result={'updates_available':rc==100,'update_count':len(rows) if rows or rc==0 else None,'held_count':None}
    save(**result,checked_at=now(),check_state='succeeded',check_error=None,progress=100)
    return result


def run_job(ident,root,state,manifests):
    if not re.fullmatch(r'[a-f0-9]{32}',ident):return 2
    state,root,manifests=map(Path,(state,root,manifests))
    file=state/(ident+'.json')
    if file.is_symlink():return 2
    job=read_json(file)
    if job.get('id')!=ident or job.get('state')!='queued':return 2
    def save(**fields):
        job.update(fields);atomic_json(file,job)
    manifest_created=False
    try:
        name=str(job['name']);action=str(job['action'])
        if action not in ('check','update','install','rebuild','delete'):raise ValueError('Invalid worker action')
        target=target_path(root,name,internal=action=='delete',missing=action in ('install','rebuild'))
        lockname=hashlib.sha256(name.encode()).hexdigest()+'.lock'
        with lock(state/'locks'/lockname,nonblocking=True):
            save(state='running',started_at=now(),progress=1,error=None)
            logfile=state/(ident+'.log')
            fd=os.open(logfile,os.O_CREAT|os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as log:
                # Explicit name is needed by run_command for bounded output reads.
                log_path=logfile
                class LoggedFile:
                    name=str(log_path)
                    def __getattr__(self,key):return getattr(log,key)
                output=LoggedFile()
                if action=='delete':
                    delete_root(job,root,state,manifests,output)
                elif action in ('install','rebuild'):
                    definition=manifests/(name+'.json')
                    if action=='install':
                        from mcp_environment_rebuild import resolve_source
                        recipe=job['manifest']
                        actual=resolve_source(recipe['base'],recipe['release'],recipe.get('source'))
                        if hashlib.sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest()!=recipe.get('source_digest'):
                            raise ValueError('Repository definition changed after review; create a new plan')
                        if target.exists():raise ValueError('Creation target already exists; it will not be replaced')
                        plan={'name':name,'manifest':job['manifest']}
                        if hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()!=job.get('plan_token'):
                            raise ValueError('Creation plan was modified')
                        manifests.mkdir(parents=True,exist_ok=True)
                        fd=os.open(definition,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
                        with os.fdopen(fd,'w') as manifest_stream:json.dump(job['manifest'],manifest_stream)
                        manifest_created=True
                    elif target.exists():assert_unused(target)
                    import mcp_environment_rebuild as builder
                    builder.ROOT=root;builder.MANIFEST=manifests
                    previous=builder.rebuild(name,ident,output,[],create_only=action=='install')
                    save(previous_environment=previous)
                else:
                    from mcp_environments import Environments
                    if action=='update':assert_unused(target)
                    with package_mounts(target,output):
                        package_operation(target,action,output,save,Environments().sources())
            save(state='completed',finished_at=now(),progress=100,exit_code=0)
        return 0
    except Exception as exc:
        if manifest_created and not (root/job.get('name','')).exists():
            (manifests/(job['name']+'.json')).unlink(missing_ok=True)
        fields={'state':'failed','finished_at':now(),'error':str(exc),'exit_code':1,'progress':0}
        if job.get('action') in ('check','update'):
            fields.update(check_state='failed',check_error=str(exc),check_attempted_at=now(),checked_at=None,updates_available=None,update_count=None)
        save(**fields)
        return 1



def rename_new(source, destination):
    """Linux atomic no-replace rename: an existing target is never overwritten."""
    import ctypes
    import errno
    libc=ctypes.CDLL(None,use_errno=True)
    try: function=libc.renameat2
    except AttributeError as exc:raise ValueError('Atomic no-replace rename is unavailable') from exc
    function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    function.restype=ctypes.c_int
    if function(-100,os.fsencode(source),-100,os.fsencode(destination),1)!=0:
        code=ctypes.get_errno()
        if code in (errno.EEXIST,errno.ENOTEMPTY):raise ValueError('Destination already exists; it will not be replaced')
        raise OSError(code,os.strerror(code),str(destination))


@contextmanager
def package_mounts(target, log):
    """Expose runtime pseudo-filesystems in the worker's private namespace only."""
    if os.readlink('/proc/self/ns/mnt')==os.readlink('/proc/1/ns/mnt'):
        raise ValueError('Package jobs require a private mount namespace')
    target=Path(target).resolve(strict=True)
    mounts=[]
    try:
        for rel in ('dev','proc','sys'):
            dest=target/rel
            if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
                raise ValueError('Unsafe runtime mount path: '+rel)
            dest.mkdir(exist_ok=True)
        # Bind only standard devices, not the appliance block devices or GPU.
        commands=[(['mount','-t','tmpfs','-o','mode=755,nosuid','tmpfs',str(target/'dev')],target/'dev')]
        for command,destination in commands:
            subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT)
            mounts.append(destination)
        for device in ('null','zero','random','urandom'):
            dest=target/'dev'/device;dest.touch()
            subprocess.run(['mount','--bind','/dev/'+device,str(dest)],check=True,stdout=log,stderr=subprocess.STDOUT)
            mounts.append(dest)
        for rel,kind,opts in [('dev/pts','devpts','newinstance,ptmxmode=0666,mode=0620'),('dev/shm','tmpfs','mode=1777,nosuid,nodev'),('proc','proc','nosuid,nodev,noexec'),('sys','sysfs','ro,nosuid,nodev,noexec')]:
            dest=target/rel;dest.mkdir(exist_ok=True)
            subprocess.run(['mount','-t',kind,'-o',opts,kind,str(dest)],check=True,stdout=log,stderr=subprocess.STDOUT)
            mounts.append(dest)
        (target/'dev/ptmx').symlink_to('pts/ptmx')
        for name,link in [('fd','/proc/self/fd'),('stdin','/proc/self/fd/0'),('stdout','/proc/self/fd/1'),('stderr','/proc/self/fd/2')]:
            (target/'dev'/name).symlink_to(link)
        yield
    finally:
        failed=[]
        for dest in reversed(mounts):
            result=subprocess.run(['umount',str(dest)],stdout=log,stderr=subprocess.STDOUT)
            if result.returncode:failed.append(str(dest))
        if failed:raise ValueError('Runtime mounts remain busy; no automatic deletion: '+', '.join(failed))
