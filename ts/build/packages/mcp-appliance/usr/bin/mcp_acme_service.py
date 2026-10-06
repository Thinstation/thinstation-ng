"""Persistent permission for the installed ACME worker, not a global vault unlock.
Local root and installed service code remain trusted. No secrets are stored here.
"""
from contextlib import contextmanager
import fcntl, hashlib, json, os, re, secrets, stat, subprocess, tempfile, time
from pathlib import Path
from mcp_login import target_rank
BASE = Path('/var/prstnt/mcp-appliance')
WORKER = '/usr/bin/mcp_acme.py'
ACTIONS = {'issue', 'renew', 'force', 'scheduled', 'test-provider'}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()

def secure_read(path, private=False):
    path = Path(path)
    for parent in (path.parent, *path.parent.parents):
        st = parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid not in (0, os.geteuid()):
            raise ValueError('Unsafe authorization path.')
        if st.st_mode & 0o022 and not (parent == Path('/tmp') and st.st_mode & stat.S_ISVTX):
            raise ValueError('Writable authorization path.')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_mode & (0o077 if private else 0o022)
                or st.st_nlink != 1 or st.st_size > 1048576):
            raise ValueError('Unsafe authorization file.')
        value = stream.read(1048577)
        if len(value) > 1048576:
            raise ValueError('Oversized authorization file.')
        return value

def atomic(path, row):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.policy-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(canonical(row) + b'\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

class ServicePolicy:
    def __init__(self, base=BASE):
        self.base = Path(base)
        self.directory = self.base / 'vault/service-authorizations'
        self.path = self.directory / 'acme.json'

    @contextmanager
    def lock(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        st = self.directory.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
            raise ValueError('Unsafe authorization directory.')
        fd = os.open(self.directory / 'acme.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            st = os.fstat(stream.fileno())
            if st.st_uid != os.geteuid() or st.st_mode & 0o077 or not stat.S_ISREG(st.st_mode):
                raise ValueError('Unsafe authorization lock.')
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def binding(self, cfg, inventory):
        if cfg.get('enabled') is not True or cfg.get('automatic') is not True:
            raise ValueError('Enable ACME and automatic renewal, then save first.')
        if cfg.get('challenge') != 'dns-01' or cfg.get('dns_provider') != 'active-directory':
            raise ValueError('Standing permission supports the built-in AD DNS provider.')
        if not cfg.get('primary_domain') or not cfg.get('accept_terms'):
            raise ValueError('Save certificate names and accept CA terms first.')
        name = cfg.get('credential', '')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name):
            raise ValueError('Choose a stored AD credential.')
        encrypted = secure_read(self.base / 'vault/credentials' / (name + '.cred'), private=True)
        raw = secure_read(self.base / 'vault/metadata' / (name + '.json'))
        metadata = json.loads(raw)
        if metadata.get('type') != 'active-directory' or not {'acme', '*'}.intersection(metadata.get('scopes') or []):
            raise ValueError('The AD credential must permit the acme scope.')
        alias = cfg.get('ad_host', '')
        host = inventory.get('hosts', {}).get(alias)
        if not isinstance(host, dict) or host.get('platform') != 'windows' or not cfg.get('ad_server'):
            raise ValueError('The saved AD DNS host is missing or invalid.')
        if target_rank(metadata, cfg['ad_server'], inventory) < 0:
            raise ValueError('The credential does not permit the selected AD DNS server.')
        groups = sorted(k for k, v in inventory.get('groups', {}).items()
                        if isinstance(v, dict) and alias in (v.get('hosts') or []))
        value = {'version': 1, 'configuration': cfg, 'host': host, 'groups': groups,
                 'metadata_sha256': hashlib.sha256(raw).hexdigest(),
                 'credential_sha256': hashlib.sha256(encrypted).hexdigest()}
        return hashlib.sha256(canonical(value)).hexdigest()

    def stored(self):
        try: row = json.loads(secure_read(self.path, private=True))
        except FileNotFoundError: return None
        if (not isinstance(row, dict) or row.get('version') != 1
                or not re.fullmatch(r'[a-f0-9]{32}', str(row.get('id', '')))
                or not re.fullmatch(r'[a-f0-9]{64}', str(row.get('binding', '')))):
            raise ValueError('Stored service authorization is invalid.')
        return row

    def status(self, cfg, inventory):
        result = {'active': False, 'present': False, 'id': None, 'revision': None,
                  'can_approve': False, 'reason': '', 'approved_at': None, 'approved_by': None}
        try:
            row = self.stored()
            if row:
                result.update(present=True, id=row['id'], approved_at=row.get('approved_at'), approved_by=row.get('approved_by'))
            current = self.binding(cfg, inventory)
            result.update(revision=current, can_approve=True)
            if row and row['binding'] == current:
                result.update(active=True, reason='ACME service authorized for this saved configuration.')
            else:
                result['reason'] = ('Configuration, target, or credential changed; approve the new settings.' if row
                                    else 'Automatic renewal is not yet authorized to use this credential.')
        except (OSError, ValueError, TypeError, KeyError):
            result['reason'] = ('Enable ACME and automatic renewal, then save before authorizing unattended use.'
                                if not cfg.get('automatic') or not cfg.get('enabled') else
                                'Credential or target is unavailable, changed, or ineligible for service authorization.')
        return result

    def audit(self, event, **fields):
        path = self.base / 'log/vault-audit.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps({'time': int(time.time()), 'event': event, **fields}, sort_keys=True) + '\n')

    def approve(self, cfg, inventory, expected, actor):
        if not isinstance(actor, str) or not actor or len(actor) > 256:
            raise ValueError('An authenticated administrator is required.')
        with self.lock():
            binding = self.binding(cfg, inventory)
            if expected != binding:
                raise ValueError('Configuration or credential changed. Refresh and confirm the new permission.')
            row = {'version': 1, 'id': secrets.token_hex(16), 'binding': binding,
                   'credential': cfg['credential'], 'approved_at': int(time.time()), 'approved_by': actor}
            self.audit('acme_service_authorize', credential=cfg['credential'], actor=actor, authorization=row['id'])
            atomic(self.path, row)
            if self.stored() != row: raise ValueError('Service authorization could not be verified.')
            return row

    def revoke(self, identifier=None, actor='configuration-change'):
        with self.lock():
            row = self.stored()
            if not row: return False
            if identifier is not None and row['id'] != identifier:
                raise ValueError('Service authorization changed. Refresh before revoking.')
            self.path.unlink()
            self.audit('acme_service_revoke', credential=row['credential'], actor=actor, authorization=row['id'])
            return True


def worker_context(command, envvar, proc=Path('/proc'), show=None):
    """Use kernel cgroup membership and the systemd MainPID, not environment flags."""
    if (envvar != 'ACME_CREDENTIAL_FILE' or len(command) != 5
            or command[:4] != ['/usr/bin/python3', '-E', WORKER, '--client'] or command[4] not in ACTIONS):
        raise ValueError('Standing permission only permits the installed ACME client command.')
    action, parent = command[4], os.getppid()
    if os.geteuid() != 0: raise ValueError('Invalid certificate service account.')
    mine = (proc / 'self/cgroup').read_text().strip()
    theirs = (proc / str(parent) / 'cgroup').read_text().strip()
    unit = 'mcp-acme-update.service' if action == 'scheduled' else 'mcp-acme-request.service'
    if mine != '0::/system.slice/' + unit or theirs != mine:
        raise ValueError('Standing permission is only available inside the certificate systemd service.')
    args = (proc / str(parent) / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    accepted = [[b'/usr/bin/python3', WORKER.encode(), b'--run', action.encode()],
                [b'/usr/bin/python3', b'-E', WORKER.encode(), b'--run', action.encode()]]
    if args not in accepted: raise ValueError('Requester is not the installed ACME worker.')
    if show is None:
        result = subprocess.run(['/usr/bin/systemctl', 'show', unit, '-p', 'MainPID', '-p', 'ControlGroup', '-p', 'ActiveState'],
                                capture_output=True, text=True, timeout=5, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        if result.returncode: raise ValueError('Certificate service identity could not be verified.')
        show = result.stdout
    properties = dict(line.split('=', 1) for line in show.splitlines() if '=' in line)
    if (properties.get('MainPID') != str(parent) or properties.get('ControlGroup') != '/system.slice/' + unit
            or properties.get('ActiveState') not in ('active', 'activating')):
        raise ValueError('Certificate worker is not the active systemd main process.')
    return action


def authorize_worker(scope, name, envvar, command):
    """Credential-release boundary: verify a pre-existing approval, never create it."""
    if scope != 'acme': raise ValueError('Standing ACME permission cannot authorize another scope.')
    worker_context(command, envvar)
    from mcp_acme import Certificates
    manager = Certificates()
    cfg = manager.config()
    if name != cfg['credential']: raise ValueError('Only the saved certificate credential may be released.')
    stage = Path(os.environ.get('MCP_ACME_STAGE', ''))
    if (stage.parent != BASE / 'state' or not stage.name.startswith('acme-stage-')
            or stage.is_symlink() or not stage.is_dir()):
        raise ValueError('Certificate staging context is missing.')
    st = stage.stat()
    if st.st_uid != 0 or st.st_mode & 0o077: raise ValueError('Unsafe certificate staging context.')
    status = ServicePolicy().status(cfg, manager.inventory())
    if not status['active']:
        raise ValueError('ACME service permission is missing, revoked, or no longer matches.')
    return status['id']
