#!/usr/bin/python3
"""Built-in AD DNS provider; GSS-TSIG only and order-scoped TXT updates."""
from contextlib import contextmanager
from mcp_certificate_names import short_names_allowed
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time

TOOLS = ('kinit', 'kvno', 'nsupdate', 'dig')
RUN = Path('/run/mcp-appliance/acme')


def tool(name):
    path = Path('/usr/libexec/mcp-ad-dns') / name
    return str(path) if path.is_file() and os.access(path, os.X_OK) else shutil.which(name)


def missing_tools():
    return [name for name in TOOLS if not tool(name)]


def fqdn(value):
    if not isinstance(value, str):
        raise ValueError('AD DNS names must be text.')
    value = value.strip().lower().rstrip('.')
    pattern = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+'
    if len(value) > 253 or not re.fullmatch(pattern, value) or all(p.isdigit() for p in value.split('.')):
        raise ValueError('Use full DNS names for the AD server, zone and realm, not IP addresses.')
    return value


def normalize_fields(cfg):
    for field in ('ad_server', 'ad_zone', 'ad_realm'):
        value = cfg[field]
        if not isinstance(value, str):
            raise ValueError('Invalid ' + field + '.')
        cfg[field] = fqdn(value) if value.strip() else ''
    cfg['ad_realm'] = cfg['ad_realm'].upper()
    for field, low, high in (('ad_ttl', 30, 3600), ('ad_propagation_timeout', 10, 180)):
        if type(cfg[field]) is not int or not low <= cfg[field] <= high:
            raise ValueError(field + ' must be an integer between ' + str(low) + ' and ' + str(high) + '.')
    return cfg


def order_domains(cfg):
    return {n.removeprefix('*.').lower().rstrip('.') for n in [cfg['primary_domain'], *cfg['alternative_names']] if n}


def owner_for(cfg, name):
    if not isinstance(name, str):
        raise ValueError('The DNS challenge name must be text.')
    name = name.removeprefix('*.').lower().rstrip('.')
    if name not in order_domains(cfg):
        raise ValueError('The DNS challenge is not part of the saved certificate order.')
    zone = cfg['ad_zone']
    if '.' not in name:
        if not short_names_allowed(cfg) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', name) or name.isdigit():
            raise ValueError('Short DNS challenge names require an internal CA.')
        if not zone:
            raise ValueError('An AD DNS zone is required to validate a short name.')
        name = name + '.' + fqdn(zone)
    name = fqdn(name)
    if not zone or not (name == zone or name.endswith('.' + zone)):
        raise ValueError('Every requested DNS name must belong to the configured AD DNS zone.')
    owner = '_acme-challenge.' + name + '.'
    if len(owner) > 254:
        raise ValueError('The DNS challenge name exceeds DNS length limits.')
    return owner


def prerequisites(cfg):
    issues = []
    missing = missing_tools()
    if missing:
        issues.append('Install the ad-dns-tools appliance package; missing: ' + ', '.join(missing) + '.')
    for field, label in (('ad_server', 'canonical AD DNS server hostname'), ('ad_zone', 'AD DNS zone'), ('ad_realm', 'Kerberos realm')):
        if not cfg[field]:
            issues.append('Enter the ' + label + '.')
    if not cfg['credential']:
        issues.append('Select an Active Directory vault credential with the acme scope.')
    if cfg['ad_zone']:
        for name in order_domains(cfg):
            try:
                owner_for(cfg, name)
            except ValueError as exc:
                issues.append(str(exc))
                break
    return issues


def invoke(argv, env, input=None, timeout=30):
    try:
        return subprocess.run(argv, input=input, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('The AD DNS operation failed or timed out. Check connectivity, DNS and clock synchronization.') from None


def principal_password(credential, realm):
    """Validate the Active Directory JSON object supplied by the vault runner."""
    if not isinstance(credential, dict) or any(not isinstance(credential.get(k), str) for k in ('domain', 'username', 'password')):
        raise ValueError('Select an Active Directory credential containing domain, username and password.')
    if fqdn(credential['domain']).upper() != realm:
        raise ValueError('The credential domain must match the configured Kerberos realm.')
    username = credential['username'].strip()
    if '\\' in username:
        prefix, username = username.split('\\', 1)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', prefix):
            raise ValueError('Invalid AD account name.')
    if '@' in username:
        username, suffix = username.rsplit('@', 1)
        if suffix.upper() != realm:
            raise ValueError('The account realm must match the provider realm.')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.\-$]{0,127}', username):
        raise ValueError('Use an account name, DOMAIN\\account, or account@REALM.')
    password = credential['password']
    if not password or len(password) > 4096 or any(c in password for c in '\x00\r\n'):
        raise ValueError('The password is empty or unsupported by noninteractive Kerberos authentication.')
    return username + '@' + realm, password


@contextmanager
def kerberos(cfg, credential, root=RUN):
    if missing_tools():
        raise ValueError('The AD DNS runtime tools are not installed.')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077:
        raise ValueError('Unsafe AD DNS runtime directory.')
    with tempfile.TemporaryDirectory(prefix='kerberos-', dir=root) as directory:
        work = Path(directory)
        conf, cache = work / 'krb5.conf', work / 'ccache'
        realm, server = cfg['ad_realm'], cfg['ad_server']
        policy = Path('/etc/crypto-policies/back-ends/krb5.config')
        text = ('include ' + str(policy) + '\n') if policy.is_file() else ''
        text += ('[libdefaults]\n default_realm = ' + realm + '\n dns_lookup_kdc = false\n dns_lookup_realm = false\n dns_canonicalize_hostname = false\n rdns = false\n forwardable = false\n proxiable = false\n ticket_lifetime = 20m\n udp_preference_limit = 1\n[realms]\n ' + realm + ' = {\n  kdc = ' + server + '\n }\n[domain_realm]\n ' + server + ' = ' + realm + '\n .' + cfg['ad_zone'] + ' = ' + realm + '\n')
        conf.write_text(text)
        conf.chmod(0o600)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('KRB5', 'GSS', 'PYTHON'))}
        env.update(KRB5_CONFIG=str(conf), KRB5CCNAME='FILE:' + str(cache), LC_ALL='C')
        principal, password = principal_password(credential, realm)
        result = invoke([tool('kinit'), '-l', '20m', '-F', '-P', principal], env, input=password + '\n', timeout=25)
        password = ''
        if result.returncode:
            raise ValueError('AD authentication failed. Check the credential, realm, canonical DC hostname, TCP 88 and clock synchronization.')
        result = invoke([tool('kvno'), 'DNS/' + server + '@' + realm], env, timeout=25)
        if result.returncode:
            raise ValueError('The DNS service ticket could not be obtained. Use the DC canonical hostname registered for its DNS service.')
        yield env
        # The ticket cache is deleted on success and exceptions by TemporaryDirectory.


class ADDNS:
    def __init__(self, cfg, env=None):
        self.cfg = cfg
        self.env = env if env is not None else os.environ.copy()

    def query(self, owner, kind):
        argv = [tool('dig'), '-r', '@' + self.cfg['ad_server'], '-q', owner, '-t', kind,
                '+tcp', '+time=3', '+tries=1', '+norecurse', '+noall', '+comments', '+answer']
        result = invoke(argv, self.env, timeout=8)
        if result.returncode or not re.search(r'status: (?:NOERROR|NXDOMAIN),', result.stdout) or not re.search(r'flags:[^;]*\baa\b', result.stdout):
            raise ValueError('The selected AD DNS server did not return an authoritative answer. Check server and zone.')
        records = []
        for line in result.stdout.splitlines():
            if not line or line.startswith(';'):
                continue
            parts = line.split(None, 4)
            if len(parts) == 5 and parts[0].lower() == owner.lower() and parts[2] == 'IN':
                records.append((parts[3], parts[4]))
        return records

    def check_zone(self):
        records = [data for kind, data in self.query(self.cfg['ad_zone'] + '.', 'SOA') if kind == 'SOA']
        if len(records) != 1:
            raise ValueError('The selected DNS server is not authoritative for the configured zone.')
        # nsupdate GSS-TSIG can use the SOA primary; do not silently choose a different DC.
        if records[0].split()[0].lower().rstrip('.') != self.cfg['ad_server']:
            raise ValueError('Select the canonical DNS server named as primary in this zone SOA record.')
        return {'ok': True, 'message': 'AD authentication, DNS service ticket and authoritative zone query passed. No DNS records were changed; write permissions are not yet proven.'}

    def values(self, owner):
        records = self.query(owner, 'TXT')
        if any(kind in ('CNAME', 'DNAME') for kind, _ in records):
            raise ValueError('The challenge name is an alias. Delegated CNAME challenges are not supported by this provider.')
        values = set()
        for kind, data in records:
            if kind == 'TXT':
                try:
                    values.add(''.join(shlex.split(data)))
                except ValueError:
                    raise ValueError('Malformed TXT response from the AD DNS server.') from None
        return values

    def update(self, owner, token, delete=False):
        if owner not in {owner_for(self.cfg, n) for n in order_domains(self.cfg)} or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise ValueError('DNS update outside the saved order or invalid TXT value.')
        operation = ('delete ' + owner + ' TXT "' + token + '"') if delete else ('add ' + owner + ' ' + str(self.cfg['ad_ttl']) + ' TXT "' + token + '"')
        text = ('server ' + self.cfg['ad_server'] + ' 53\nzone ' + self.cfg['ad_zone'] + '.\nrealm ' + self.cfg['ad_realm'] + '\nupdate ' + operation + '\nsend\n')
        result = invoke([tool('nsupdate'), '-g', '-v', '-t', '20'], self.env, input=text, timeout=30)
        if result.returncode:
            raise ValueError('Secure AD DNS update failed. Check delegated write permission on the required _acme-challenge records and TCP 53. No unsigned fallback was attempted.')

    def hook(self, event, name, token, stage):
        if event not in ('deploy_challenge', 'clean_challenge') or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise ValueError('Invalid DNS-01 hook event or TXT value.')
        owner = owner_for(self.cfg, name)
        stage = Path(stage)
        marker = stage / ('ad-dns-' + hashlib.sha256((owner + '\0' + token).encode()).hexdigest() + '.json')
        if event == 'clean_challenge':
            if not marker.is_file():
                return 0
            self.update(owner, token, delete=True)
            marker.unlink()
            return 0
        self.check_zone()
        if token in self.values(owner):
            return 0  # Do not take ownership of a pre-existing value.
        marker.write_text(json.dumps({'owner': owner, 'domain': name, 'token': token}))
        marker.chmod(0o600)
        try:
            self.update(owner, token)
            deadline = time.monotonic() + self.cfg['ad_propagation_timeout']
            while time.monotonic() < deadline:
                if token in self.values(owner):
                    return 0
                time.sleep(2)
            raise ValueError('The challenge TXT value did not become visible on the AD DNS server before timeout.')
        except Exception:
            try:
                self.update(owner, token, delete=True)
                marker.unlink(missing_ok=True)
            except Exception:
                pass  # Retain the marker for a final cleanup attempt.
            raise

    def cleanup(self, stage):
        failed = False
        for marker in Path(stage).glob('ad-dns-*.json'):
            try:
                row = json.loads(marker.read_text())
                self.hook('clean_challenge', row['domain'], row['token'], stage)
            except Exception:
                failed = True
        if failed:
            raise ValueError('AD DNS cleanup failed. A challenge TXT value may remain; certificate installation was stopped.')
