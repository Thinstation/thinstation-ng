#!/usr/bin/python3
"""Scoped ACME service authorization.

Stores only an approval fingerprint; never stores or decrypts credential material.
"""
import hashlib, json, os, re, tempfile, time
from pathlib import Path
from mcp_login import target_rank

BASE=Path('/var/prstnt/mcp-appliance')

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()

def read_bytes(path, private=False, limit=1048576):
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        st=os.fstat(stream.fileno())
        if not os.path.isfile(path) or st.st_uid not in (0,os.geteuid()) or st.st_nlink!=1 or st.st_size>limit:
            raise ValueError('Unsafe authorization input.')
        if private and st.st_mode&0o077:
            raise ValueError('Credential file permissions are unsafe.')
        if not private and st.st_mode&0o022:
            raise ValueError('Authorization input is writable by an untrusted account.')
        data=stream.read(limit+1)
        if len(data)>limit: raise ValueError('Authorization input is too large.')
        return data

def atomic(path,row):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path.parent,0o700)
    fd,tmp=tempfile.mkstemp(prefix='.acme-authorization-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600)
            stream.write(canonical(row)+b'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

class ACMEAuthorization:
    def __init__(self,base=BASE):
        self.base=Path(base)
        self.path=self.base/'vault/service-authorizations/acme.json'
        self.audit_path=self.base/'log/vault-audit.jsonl'

    def binding(self,cfg,inventory):
        if cfg.get('enabled') is not True or cfg.get('automatic') is not True:
            raise ValueError('Enable ACME and automatic renewal, then save before authorizing unattended renewal.')
        if cfg.get('challenge')!='dns-01' or cfg.get('dns_provider')!='active-directory':
            raise ValueError('Standing authorization is only needed for Active Directory DNS credentials.')
        name=cfg.get('credential','')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',name):
            raise ValueError('Select a saved Active Directory credential.')
        raw_meta=read_bytes(self.base/'vault/metadata'/(name+'.json'))
        encrypted=read_bytes(self.base/'vault/credentials'/(name+'.cred'),private=True)
        meta=json.loads(raw_meta)
        if meta.get('type')!='active-directory' or not {'acme','*'}.intersection(meta.get('scopes') or []):
            raise ValueError('The selected credential must be Active Directory and allow the acme scope.')
        alias=cfg.get('ad_host','')
        host=inventory.get('hosts',{}).get(alias)
        if not isinstance(host,dict) or host.get('platform')!='windows':
            raise ValueError('The saved AD DNS target is unavailable.')
        if target_rank(meta,cfg.get('ad_server',''),inventory)<0:
            raise ValueError('The credential no longer permits the saved AD DNS target.')
        bound={
          'version':1,
          'configuration':cfg,
          'inventory_host':host,
          'credential_metadata_sha256':hashlib.sha256(raw_meta).hexdigest(),
          'encrypted_credential_sha256':hashlib.sha256(encrypted).hexdigest()
        }
        return hashlib.sha256(canonical(bound)).hexdigest()

    def stored(self):
        try:
            row=json.loads(read_bytes(self.path,private=True))
        except FileNotFoundError:
            return None
        if not isinstance(row,dict) or row.get('version')!=1:
            raise ValueError('Stored ACME authorization is invalid.')
        return row

    def status(self,cfg,inventory):
        out={'automatic_authorized':False,'can_authorize_automatic':False,'revision':None,'authorization_id':None,'approved_at':None,'approved_by':None,'reason':''}
        try:
            current=self.binding(cfg,inventory)
            out.update(revision=current,can_authorize_automatic=True)
            row=self.stored()
            if row:
                out.update(authorization_id=row.get('id'),approved_at=row.get('approved_at'),approved_by=row.get('approved_by'))
                if row.get('binding')==current and row.get('credential')==cfg.get('credential'):
                    out['automatic_authorized']=True
                    out['reason']='Automatic renewal is authorized for this saved ACME configuration.'
                else:
                    out['reason']='Saved ACME settings, target, or credential changed; authorize automatic renewal again.'
            else:
                out['reason']='Automatic renewal has not been authorized to use the saved credential.'
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
            out['reason']=str(exc) or 'Automatic authorization is unavailable.'
        return out

    def audit(self,event,**fields):
        self.audit_path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.audit_path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a') as stream:
            os.fchmod(stream.fileno(),0o600)
            stream.write(json.dumps({'time':int(time.time()),'event':event,**fields},sort_keys=True)+'\n')

    def authorize(self,cfg,inventory,expected_revision,actor):
        binding=self.binding(cfg,inventory)
        if expected_revision!=binding:
            raise ValueError('Saved ACME configuration changed. Refresh and review before authorizing.')
        row={'version':1,'id':os.urandom(16).hex(),'binding':binding,'credential':cfg['credential'],'approved_at':int(time.time()),'approved_by':actor}
        atomic(self.path,row)
        self.audit('acme_service_authorize',credential=cfg['credential'],actor=actor,authorization=row['id'])
        return row

    def revoke(self,actor):
        row=self.stored()
        if not row:return False
        self.path.unlink()
        self.audit('acme_service_revoke',credential=row.get('credential'),actor=actor,authorization=row.get('id'))
        return True

def scheduled_worker_authorized(scope,name,envvar,command,base=BASE,proc=Path('/proc')):
    if scope!='acme' or envvar!='ACME_CREDENTIAL_FILE':
        return False
    expected=['/usr/bin/python3','/usr/bin/mcp_acme.py','--client','scheduled']
    if command!=expected or os.geteuid()!=0:
        return False
    try:
        parent=os.getppid()
        cgroup=(proc/'self/cgroup').read_text().strip()
        parent_group=(proc/str(parent)/'cgroup').read_text().strip()
        if cgroup!='0::/system.slice/mcp-acme-update.service' or parent_group!=cgroup:
            return False
        argv=[x.decode() for x in (proc/str(parent)/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')]
        if argv not in (
          ['/usr/bin/python3','/usr/bin/mcp_acme.py','--run','scheduled'],
          ['/usr/bin/python3','-E','/usr/bin/mcp_acme.py','--run','scheduled']
        ):
            return False
        from mcp_acme import Certificates
        manager=Certificates(base=base)
        cfg=manager.config()
        if cfg.get('credential')!=name:
            return False
        return ACMEAuthorization(base).status(cfg,manager.inventory()).get('automatic_authorized') is True
    except Exception:
        return False
