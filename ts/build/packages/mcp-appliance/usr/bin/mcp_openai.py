"""One explicitly configured OpenAI private tunnel per appliance.

This service never reads, imports or stops another tunnel client's configuration.
The key is write-only, TPM-encrypted at rest and delivered by systemd credentials.
The only MCP target is the appliance's loopback MCP; Harpoon is disabled.
"""
import datetime
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.parse import urlparse
import zipfile

BASE = Path('/var/prstnt/mcp-appliance')
UNIT = 'mcp-openai-tunnel.service'
RUN = Path('/run/mcp-openai-tunnel')
VERSION = '0.0.15'
ARCHIVE_SHA256 = 'f26f8b3ee6c335e38fa5cfbe6ce5635f53738f08a26eecf07d6cebacab4a1abf'
ARCHIVE_URL = 'https://github.com/openai/tunnel-client/releases/download/v0.0.15/tunnel-client-runtime-v0.0.15-linux-amd64.zip'
LOCAL_MCP = 'http://127.0.0.1:8000/mcp'


def normalize_tunnel(value):
    value = str(value or '').strip()
    if value.startswith('https://'):
        url = urlparse(value)
        if url.hostname not in ('api.openai.com', 'platform.openai.com') or url.username or url.password or url.port not in (None, 443):
            raise ValueError('Use an OpenAI tunnel ID, not a custom server URL.')
        matches = re.findall(r'tunnel_[A-Za-z0-9_-]{8,128}', url.path)
        if len(matches) != 1:
            raise ValueError('This URL does not contain a tunnel ID. An OAuth callback URL is not a tunnel ID.')
        value = matches[0]
    if not re.fullmatch(r'tunnel_[A-Za-z0-9_-]{8,128}', value):
        raise ValueError('Enter the tunnel_... identifier from OpenAI tunnel settings.')
    return value


def age_seconds(value, now=None):
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return None
        age = (time.time() if now is None else now) - dt.timestamp()
        return age if -5 <= age else None
    except (ValueError, TypeError):
        return None


def health_summary(service, enabled, snapshot, now=None):
    """A live process or readyz response alone does not prove OpenAI connectivity."""
    answer = {'state': 'disconnected', 'label': 'Disconnected', 'tone': 'neutral',
              'detail': 'Saved configuration is not connected.', 'last_poll_success': None,
              'last_request': None, 'last_response_accepted': None, 'request_evidence': False,
              'local_probe_state': 'unknown'}
    if not enabled:
        if service in ('active', 'activating', 'deactivating'):
            answer.update(state='disconnecting', label='Disconnecting', detail='Waiting for the tunnel service to stop.')
        return answer
    if service != 'active':
        answer.update(state='starting' if service == 'activating' else 'service_unavailable',
                      label='Starting' if service == 'activating' else 'Tunnel service not running',
                      tone='warn', detail='Reconnect or inspect the tunnel service. The MCP runtime is independent.')
        return answer
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != 1 or snapshot.get('live') is not True:
        answer.update(state='checking', label='Connection status unavailable', tone='warn', detail='The tunnel is running, but no valid health evidence is available yet.')
        return answer
    freshness = age_seconds(snapshot.get('snapshot_at'), now)
    if freshness is None or freshness > 30:
        answer.update(state='stale', label='Connection status stale', tone='warn', detail='Refresh to obtain current tunnel evidence.')
        return answer
    components = snapshot.get('components') or {}
    control = components.get('control-plane') or {}
    poll = control.get('details') or {}
    queue = (components.get('queue') or {}).get('details') or {}
    delivery = (components.get('response-delivery') or {}).get('details') or {}
    answer.update(last_poll_success=poll.get('last_success'), last_request=queue.get('last_enqueue'),
                  last_response_accepted=delivery.get('last_accepted'), request_evidence=bool(queue.get('last_enqueue')),
                  local_probe_state=(components.get('mcp') or {}).get('state', 'unknown'))
    code = poll.get('http_status')
    if control.get('status') == 'degraded':
        detail = {401: 'OpenAI rejected the runtime key. Disconnect, edit the key, then reconnect.',
                  403: 'Check tunnel Use permission and the owning OpenAI organization.',
                  404: 'Check the tunnel ID, organization and workspace associations.'}.get(code,
                  'The tunnel cannot currently poll OpenAI. It will retry automatically; check outbound HTTPS access.')
        answer.update(state='retrying', label='Connection needs attention', tone='warn', detail=detail)
    elif control.get('status') == 'ok' and age_seconds(poll.get('last_success'), now) is not None and age_seconds(poll.get('last_success'), now) <= 120:
        answer.update(state='connected', label='Connected to OpenAI', tone='good',
                      detail='An authenticated OpenAI poll succeeded. Select this tunnel in the intended ChatGPT workspace; a poll is not proof of a ChatGPT tool call.')
    else:
        answer.update(state='connecting', label='Connecting to OpenAI', tone='neutral', detail='Waiting for the first successful authenticated poll.')
    return answer


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=1)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(1)
        self.sock.connect(self.path)


class OpenAITunnel:
    def __init__(self, operator, base=BASE):
        self.operator = operator
        self.base = Path(base)
        self.root = self.base / 'connections/openai'
        self.current = self.root / 'current'
        self.enabled = self.root / 'enabled'
        self.component = self.base / 'components/openai-tunnel' / VERSION
        self.lock = threading.RLock()

    def _read(self):
        if not self.current.exists():
            return None
        self.current.resolve().relative_to(self.root.resolve())
        row = json.loads((self.current / 'profile.json').read_text())
        normalize_tunnel(row['tunnel_id'])
        return row

    def _unit_state(self):
        result = subprocess.run(['/usr/bin/systemctl', 'is-active', UNIT], capture_output=True, text=True, timeout=4)
        value = result.stdout.strip()
        return value if value in ('active', 'activating', 'deactivating', 'failed', 'inactive') else 'unknown'

    def _health(self):
        conn = UnixHTTPConnection(RUN / 'health.sock')
        try:
            conn.request('GET', '/health?details=true')
            response = conn.getresponse()
            data = response.read(65537)
            if response.status != 200 or len(data) > 65536:
                return None
            return json.loads(data)
        except (OSError, ValueError, http.client.HTTPException):
            return None
        finally:
            conn.close()

    def runtime_installed(self):
        return (self.component / 'tunnel-client-runtime').is_file() and (self.component / 'verified.json').is_file()

    def status(self):
        with self.lock:
            profile = self._read()
            service = self._unit_state()
            state = health_summary(service, self.enabled.exists(), self._health() if service == 'active' else None)
            return {'configured': profile is not None,
                    'profile': {k: profile.get(k) for k in ('name', 'tunnel_id', 'organization_id', 'saved_at')} if profile else None,
                    'credential_saved': bool(profile and (self.current / 'api-key.cred').is_file()),
                    'credential_protection': 'TPM-encrypted service credential',
                    'tpm_available': Path('/dev/tpmrm0').exists() or Path('/dev/tpm0').exists(),
                    'runtime_installed': self.runtime_installed(), 'runtime_version': VERSION,
                    'enabled': self.enabled.exists(), 'service': service, 'connection': state,
                    'local_mcp': LOCAL_MCP,
                    'permissions': 'All tools exposed by this appliance MCP; target credentials and vault rules still apply.',
                    'scope': 'One dedicated OpenAI tunnel for this appliance. Other tunnel clients are not imported or modified.'}

    def _control(self, action):
        if action not in ('start', 'restart', 'stop'):
            raise ValueError('Unsupported tunnel action.')
        p = subprocess.run(['/usr/bin/systemctl', action, UNIT], capture_output=True, timeout=25)
        if p.returncode:
            raise ValueError('Tunnel service action failed. Inspect mcp-openai-tunnel.service; saved settings were retained.')

    def save(self, body):
        with self.lock:
            if not os.path.ismount('/var/prstnt'):
                raise ValueError('Provision persistent storage before saving a connection.')
            if self.enabled.exists() or self._unit_state() in ('active', 'activating', 'deactivating'):
                raise ValueError('Disconnect this appliance tunnel before editing its settings.')
            if body.get('confirm_full_access') is not True or body.get('confirm_dedicated_tunnel') is not True:
                raise ValueError('Confirm access and that this tunnel is dedicated to this appliance.')
            name = str(body.get('name', '')).strip()
            if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
                raise ValueError('Enter a connection name of 1 to 100 characters.')
            tid = normalize_tunnel(body.get('tunnel_id'))
            org = str(body.get('organization_id') or '').strip()
            if org and not re.fullmatch(r'org-[A-Za-z0-9_-]{5,100}', org):
                raise ValueError('Enter a valid optional org-... organization ID.')
            key = str(body.get('api_key') or '').strip()
            previous = self._read()
            if not key and not previous:
                raise ValueError('A runtime API key is required for the first connection.')
            if not key and previous and previous['tunnel_id'] != tid:
                raise ValueError('Provide the runtime key again when changing the tunnel ID.')
            if key and (not 20 <= len(key) <= 1024 or not re.fullmatch(r'[A-Za-z0-9_.-]+', key)):
                raise ValueError('Paste the runtime API key itself, not an environment assignment or file reference.')
            self.root.mkdir(parents=True, exist_ok=True)
            self.root.chmod(0o700)
            stage = Path(tempfile.mkdtemp(prefix='profile-', dir=self.root))
            before = self.current.resolve() if self.current.exists() else None
            try:
                credential = stage / 'api-key.cred'
                if key:
                    if not (Path('/dev/tpmrm0').exists() or Path('/dev/tpm0').exists()):
                        raise ValueError('TPM-backed credential storage is unavailable. Attach a TPM 2.0 device before saving this connection.')
                    p = subprocess.run(['/usr/bin/systemd-creds', 'encrypt', '--with-key=tpm2', '--tpm2-pcrs=', '--name=openai-api-key', '-', str(credential)], input=key.encode(), capture_output=True, timeout=30)
                    key = ''
                    if p.returncode:
                        raise ValueError('The runtime key could not be encrypted with the appliance TPM. No connection was changed.')
                else:
                    shutil.copyfile(self.current / 'api-key.cred', credential)
                credential.chmod(0o600)
                row = {'name': name, 'tunnel_id': tid, 'organization_id': org, 'saved_at': int(time.time()), 'full_access_acknowledged': True}
                self.operator._write(stage / 'profile.json', row)
                link = self.root / ('.current-' + stage.name)
                link.symlink_to(stage.name)
                os.replace(link, self.current)
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise
            finally:
                key = ''
            if before and before != stage and before.parent == self.root and before.name.startswith('profile-'):
                shutil.rmtree(before)
            self.operator._event('tunnel-configured', name, 'Dedicated ChatGPT tunnel settings saved. Not connected yet.')
            return {'ok': True, 'message': 'Saved. Connect when the tunnel is associated with the intended workspace.', 'status': self.status()}

    def install_runtime(self):
        with self.lock:
            if self.runtime_installed():
                return {'ok': True, 'status': self.status()}
            if os.uname().machine not in ('x86_64', 'amd64'):
                raise ValueError('This reviewed runtime package supports x86-64 appliances only.')
            if not os.path.ismount('/var/prstnt'):
                raise ValueError('Provision persistent storage first.')
            parent = self.component.parent
            parent.mkdir(parents=True, exist_ok=True)
            parent.chmod(0o700)
            with tempfile.TemporaryDirectory(prefix='.download-', dir=parent) as temp:
                temp = Path(temp)
                archive = temp / 'runtime.zip'
                p = subprocess.run(['/usr/bin/curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '10', '--max-time', '120', '--max-filesize', '104857600', '-o', str(archive), ARCHIVE_URL], capture_output=True, timeout=130)
                if p.returncode:
                    raise ValueError('Could not download the reviewed OpenAI runtime release. Check outbound HTTPS access and retry.')
                if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
                    raise ValueError('OpenAI runtime checksum mismatch; nothing was installed.')
                unpacked = temp / 'unpacked'
                unpacked.mkdir()
                with zipfile.ZipFile(archive) as z:
                    if len(z.infolist()) > 20 or sum(x.file_size for x in z.infolist()) > 150 * 1024 * 1024:
                        raise ValueError('Unexpected runtime archive size.')
                    for item in z.infolist():
                        mode = item.external_attr >> 16
                        if '/' in item.filename or '\\' in item.filename or item.filename in ('.', '..') or stat.S_ISLNK(mode):
                            raise ValueError('Unexpected runtime archive layout.')
                    z.extractall(unpacked)
                binary = unpacked / 'tunnel-client-runtime'
                if not binary.is_file() or not (unpacked / 'LICENSE').is_file():
                    raise ValueError('Runtime or license missing from the verified archive.')
                binary.chmod(0o755)
                self.operator._write(unpacked / 'verified.json', {'version': VERSION, 'archive_sha256': ARCHIVE_SHA256, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()})
                if self.component.exists():
                    raise ValueError('Incomplete runtime directory already exists; inspect before replacing it.')
                os.replace(unpacked, self.component)
            self.operator._event('tunnel-runtime-installed', 'ChatGPT', 'Verified OpenAI tunnel runtime ' + VERSION + ' installed with upstream licenses. No tunnel was started.')
            return {'ok': True, 'status': self.status()}

    def action(self, action):
        with self.lock:
            profile = self._read()
            if not profile:
                raise ValueError('Save the dedicated tunnel ID and runtime key first.')
            if action == 'disconnect':
                self.enabled.unlink(missing_ok=True)
                self._control('stop')
            elif action in ('connect', 'reconnect'):
                if not self.runtime_installed():
                    raise ValueError('Install the OpenAI connection component first.')
                if not (self.current / 'api-key.cred').is_file():
                    raise ValueError('The saved runtime credential is missing; edit the connection.')
                self.operator._write(self.enabled, {'enabled_at': int(time.time())})
                self._control('restart' if action == 'reconnect' else 'start')
            else:
                raise ValueError('Unsupported tunnel action.')
            self.operator._event('tunnel-' + action, profile['name'], 'Appliance tunnel action: ' + action + '. Other tunnel clients are unaffected.')
            return {'ok': True, 'status': self.status()}


def run_tunnel():
    """systemd entrypoint. No user-provided command or remote URL is executed."""
    credentials = Path(os.environ['CREDENTIALS_DIRECTORY'])
    row = json.loads((credentials / 'openai-profile').read_text())
    tid = normalize_tunnel(row['tunnel_id'])
    component = BASE / 'components/openai-tunnel' / VERSION
    binary = component / 'tunnel-client-runtime'
    verified = json.loads((component / 'verified.json').read_text())
    if verified.get('archive_sha256') != ARCHIVE_SHA256 or hashlib.sha256(binary.read_bytes()).hexdigest() != verified.get('binary_sha256'):
        raise RuntimeError('Reviewed OpenAI runtime integrity check failed.')
    argv = [str(binary), 'run', '--control-plane.base-url=https://api.openai.com',
            '--control-plane.tunnel-id=' + tid,
            '--control-plane.api-key=file:' + str(credentials / 'openai-api-key'),
            '--control-plane.poll-channel=main', '--mcp.server-url=' + LOCAL_MCP,
            '--harpoon.hosts-include-loopback=false', '--harpoon.hosts-include-private=false',
            '--health.unix-socket=' + str(RUN / 'health.sock'), '--health.show-details=true',
            '--log.level=warn', '--log.format=json', '--log.http-raw-unsafe=false']
    org = row.get('organization_id')
    if org:
        if not re.fullmatch(r'org-[A-Za-z0-9_-]{5,100}', org):
            raise ValueError('Invalid saved organization ID.')
        argv.append('--control-plane.organization-id=' + org)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(RUN), 'LANG': 'C.UTF-8', 'NO_PROXY': '127.0.0.1,localhost'}
    os.execve(binary, argv, env)


if __name__ == '__main__':
    if sys.argv[1:] != ['--run']:
        raise SystemExit('usage: mcp_openai.py --run (systemd only)')
    try:
        run_tunnel()
    except Exception:
        # Never emit config/credential objects into the journal.
        raise SystemExit('OpenAI tunnel startup failed; check component integrity and saved service credentials.')
