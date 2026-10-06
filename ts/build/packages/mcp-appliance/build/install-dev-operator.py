#!/usr/bin/python3
"""Install a pinned paired UI/backend on the development appliance.

Only the management web service is restarted. An active appliance tunnel blocks
installation; this utility never reads tunnel keys or starts any tunnel. The
unit and web override are runtime-only and revert on reboot of the older ISO.
"""
import argparse
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import py_compile
import re
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlsplit

BASE = Path('/var/prstnt/mcp-appliance')
DROPIN = Path('/run/systemd/system/mcp-appliance-web.service.d/50-operator-dev.conf')
TUNNEL_UNIT = Path('/run/systemd/system/mcp-openai-tunnel.service')
BACKEND_FILES = {'mcp_operator.py', 'mcp-operator-web', 'mcp-appliance-web', 'mcp_inventory.py', 'mcp_login.py',
                 'mcp_openai.py', 'mcp_acme.py', 'mcp_acme_authorization.py', 'mcp_ad_dns.py', 'mcp_http01.py', 'mcp_tlsalpn.py', 'mcp_certificate_form.py', 'mcp_certificate_names.py', 'mcp_storage.py', 'mcp_storage_worker.py', 'mcp-openai-tunnel.service', 'install-dev-operator.py'}
UNIT_TEMPLATE = '''[Unit]
Description=Dedicated appliance OpenAI MCP tunnel
After=network-online.target mcp-appliance-init.service mcp-runtime.service
Wants=network-online.target
RequiresMountsFor=/var/prstnt/mcp-appliance
ConditionPathExists=/var/prstnt/mcp-appliance/connections/openai/enabled

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/bin/mcp_openai.py --run
LoadCredentialEncrypted=openai-api-key:/var/prstnt/mcp-appliance/connections/openai/current/api-key.cred
LoadCredential=openai-profile:/var/prstnt/mcp-appliance/connections/openai/current/profile.json
RuntimeDirectory=mcp-openai-tunnel
RuntimeDirectoryMode=0700
UMask=0077
Restart=on-failure
RestartSec=10
TimeoutStopSec=20
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
'''


def command(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=40).stdout.strip()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data if isinstance(data, bytes) else data.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def local_request(path):
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(BASE / 'identity/web.crt'))
    context.check_hostname = False  # Loopback check pins this appliance's certificate.
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    conn = http.client.HTTPSConnection('127.0.0.1', 8443, context=context, timeout=5)
    try:
        conn.request('GET', path)
        response = conn.getresponse()
        return response.status, response.read(1024 * 1024)
    finally:
        conn.close()


def verify_bundle(archive, web, sha, pipeline, digest):
    if not re.fullmatch(r'[0-9a-f]{64}', digest) or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise ValueError('Archive checksum does not match the independently supplied build digest.')
    web.mkdir()
    with tarfile.open(archive) as tf:
        members = tf.getmembers()
        if len(members) > 250 or sum(m.size for m in members) > 20 * 1024 * 1024:
            raise ValueError('Unexpected development archive size.')
        seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            normalized = str(path)
            if path.is_absolute() or '..' in path.parts or '\\' in member.name or any(ord(c) < 32 for c in member.name):
                raise ValueError('Unsafe archive path.')
            if normalized in seen:
                raise ValueError('Duplicate archive entry.')
            seen.add(normalized)
            if not (member.isfile() or member.isdir()):
                raise ValueError('Archive contains a link or special file.')
            (web / member.name).resolve().relative_to(web.resolve())
        tf.extractall(web, filter='data')
    manifest = json.loads((web / 'operator-release.json').read_text())
    if manifest.get('version') != 1 or manifest.get('source_sha') != sha or str(manifest.get('pipeline')) != pipeline:
        raise ValueError('Published bundle does not match the requested build.')
    expected = manifest.get('files')
    if not isinstance(expected, dict):
        raise ValueError('Invalid release manifest.')
    actual = {p.relative_to(web).as_posix() for p in web.rglob('*') if p.is_file()} - {'operator-release.json'}
    if set(expected) != actual:
        raise ValueError('Release manifest does not cover exactly the extracted files.')
    for name, value in expected.items():
        path = web / name
        path.resolve().relative_to(web.resolve())
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) or hashlib.sha256(path.read_bytes()).hexdigest() != value:
            raise ValueError('Release file checksum mismatch.')
    if not (web / 'index.html').is_file():
        raise ValueError('Frontend is incomplete.')
    backend = web / '_operator'
    if not backend.is_dir() or {p.name for p in backend.iterdir()} != BACKEND_FILES:
        raise ValueError('Unexpected paired backend files.')
    if (backend / 'mcp-openai-tunnel.service').read_text() != UNIT_TEMPLATE:
        raise ValueError('Tunnel service differs from the reviewed template.')
    for path in backend.iterdir():
        if not path.is_file():
            raise ValueError('Backend entry is not a regular file.')
        if path.name != 'mcp-openai-tunnel.service':
            py_compile.compile(str(path), doraise=True)
    return manifest


def require_idle_tunnel():
    if (BASE / 'connections/openai/enabled').exists():
        raise ValueError('Disconnect the appliance tunnel before replacing its development code.')
    value = subprocess.run(['/usr/bin/systemctl', 'is-active', 'mcp-openai-tunnel.service'], capture_output=True, text=True, timeout=5).stdout.strip()
    if value not in ('inactive', 'failed', 'unknown'):
        raise ValueError('Appliance tunnel must be confirmed inactive; no service was changed.')


def install(url, sha, pipeline, digest):
    if os.geteuid() != 0:
        raise ValueError('Run as root on the development appliance.')
    if not os.path.ismount('/var/prstnt'):
        raise ValueError('Persistent storage must be mounted.')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Use an HTTPS build URL without embedded credentials.')
    if not re.fullmatch(r'[0-9a-f]{40}', sha) or not pipeline.isdigit() or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Specify the exact source commit, pipeline number and archive SHA-256.')
    require_idle_tunnel()
    for path in (DROPIN, TUNNEL_UNIT):
        if path.is_symlink():
            raise ValueError('Refusing to replace a symlinked runtime override.')
    releases = BASE / 'dev-releases'
    releases.mkdir(parents=True, exist_ok=True)
    release = releases / ('operator-' + pipeline + '-' + sha[:8])
    if release.exists():
        raise ValueError('Release directory already exists; inspect before retrying.')
    with tempfile.TemporaryDirectory(prefix='.operator-', dir=releases) as temporary:
        stage = Path(temporary)
        archive = stage / 'bundle.tar.gz'
        command(['/usr/bin/curl', '--fail', '--silent', '--show-error', '--proto', '=https', '--connect-timeout', '10', '--max-time', '30', '--max-filesize', '20971520', '-o', str(archive), url])
        web = stage / 'web'
        verify_bundle(archive, web, sha, pipeline, digest)
        backend = stage / 'backend'
        (web / '_operator').rename(backend)
        release.mkdir(mode=0o700)
        shutil.move(str(web), release / 'web')
        shutil.move(str(backend), release / 'backend')
    require_idle_tunnel()
    prior = {path: path.read_bytes() if path.exists() else None for path in (DROPIN, TUNNEL_UNIT)}
    runtime_pid = command(['/usr/bin/systemctl', 'show', 'mcp-runtime.service', '-p', 'MainPID', '--value'])
    runtime_state = BASE / 'state/mcp-runtime.state'
    before_state = runtime_state.read_bytes() if runtime_state.exists() else None
    template = UNIT_TEMPLATE.replace('ExecStart=/usr/bin/python3 /usr/bin/mcp_openai.py --run',
                                     'ExecStart=/usr/bin/python3 ' + str(release / 'backend/mcp_openai.py') + ' --run')
    override = '[Service]\nEnvironment=MCP_OPERATOR_WEB_ROOT=' + str(release / 'web') + '\nExecStart=\nExecStart=/usr/bin/python3 ' + str(release / 'backend/mcp-operator-web') + '\n'
    try:
        atomic_write(TUNNEL_UNIT, template)
        atomic_write(DROPIN, override)
        command(['/usr/bin/systemctl', 'daemon-reload'])
        command(['/usr/bin/systemctl', 'restart', 'mcp-appliance-web.service'])
        for attempt in range(10):
            try:
                status, html = local_request('/')
                if status == 200 and html == (release / 'web/index.html').read_bytes():
                    break
            except (OSError, ssl.SSLError):
                pass
            time.sleep(.5)
        else:
            raise RuntimeError('New frontend did not become available.')
        for path in ('/api/operator/connections', '/api/operator/openai'):
            status, body = local_request(path)
            if status != 401 or json.loads(body).get('error') != 'Administrator sign-in required.':
                raise RuntimeError('Operator authentication check failed.')
        require_idle_tunnel()
        if command(['/usr/bin/systemctl', 'show', 'mcp-runtime.service', '-p', 'MainPID', '--value']) != runtime_pid:
            raise RuntimeError('MCP runtime changed during web deployment.')
        if (runtime_state.read_bytes() if runtime_state.exists() else None) != before_state:
            raise RuntimeError('MCP runtime state changed during web deployment.')
    except Exception:
        for path, value in prior.items():
            if value is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, value)
        command(['/usr/bin/systemctl', 'daemon-reload'])
        command(['/usr/bin/systemctl', 'restart', 'mcp-appliance-web.service'])
        raise
    print(json.dumps({'ok': True, 'source_sha': sha, 'pipeline': pipeline, 'release': str(release),
                      'frontend_verified': True, 'anonymous_operator_access_denied': True,
                      'mcp_runtime_unchanged': True, 'tunnel_not_started': True,
                      'existing_dev_web_preserved': True, 'reboot_reverts_dev_override': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--pipeline', required=True)
    parser.add_argument('--archive-sha256', required=True)
    args = parser.parse_args()
    with open('/run/mcp-operator-install.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install(args.url, args.source_sha, args.pipeline, args.archive_sha256)
