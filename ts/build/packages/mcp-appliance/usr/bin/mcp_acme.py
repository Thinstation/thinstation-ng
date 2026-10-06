#!/usr/bin/python3
"""Persistent, validated settings and isolated jobs for dehydrated.

DNS hooks are installed by an administrator, never uploaded or evaluated
through the settings form. Credential values are never accepted by this API.
"""
import argparse
import mcp_http01 as http01
import mcp_tlsalpn as tlsalpn
import mcp_certificate_form as certificate_form
from mcp_certificate_names import short_names_allowed, appliance_identity
from mcp_login import target_rank
import mcp_ad_dns as ad_dns
from mcp_acme_authorization import ACMEAuthorization
from contextlib import contextmanager
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

BASE = Path('/var/prstnt/mcp-appliance')
NATIVE = Path('/etc/mcp-appliance/acme.conf')
LE = 'https://acme-v02.api.letsencrypt.org/directory'
STAGING = 'https://acme-staging-v02.api.letsencrypt.org/directory'
DEFAULTS = dict(enabled=False, automatic=False, directory_url=LE, internal_ca=False, email='',
                primary_domain='', alternative_names=[], challenge='dns-01',
                dns_hook='', credential='', key_algorithm='prime256v1',
                renew_days=30, accept_terms=False, http_ready=False, test_only=False,
                dns_provider='active-directory', ad_host='', ad_server='', ad_zone='', ad_realm='',
                ad_ttl=60, ad_propagation_timeout=60,
                http_mode='standalone', http_source_networks=[], http_public_access=False,
                alpn_ready=False, alpn_source_networks=[], alpn_public_access=False)


def atomic(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data.encode() if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def command(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, timeout=15, **kwargs)


def domain(value, wildcard=False, allow_short=False):
    if not isinstance(value, str):
        raise ValueError('Certificate names must be text.')
    value = certificate_form.bare_name(value).strip().lower().rstrip('.')
    prefix = '*.' if wildcard and value.startswith('*.') else ''
    name = value[2:] if prefix else value
    try:
        name = name.encode('idna').decode('ascii')
    except UnicodeError:
        raise ValueError('Invalid international domain name.') from None
    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    if (len(name) > 253 or not re.fullmatch(label + r'(?:\.' + label + ')*', name)
            or ('.' not in name and (not allow_short or prefix))):
        raise ValueError('Use a fully qualified DNS name; a short hostname requires an internal CA. IP addresses, paths, and short-name wildcards are not accepted.')
    if name == 'localhost' or name.endswith('.localhost') or name == 'localhost.localdomain':
        raise ValueError('Loopback hostnames cannot be used as appliance certificate names.')
    if all(part.isdigit() for part in name.split('.')):
        raise ValueError('IP-address certificates are not supported by this interface.')
    return prefix + name


def normalize(body):
    if not isinstance(body, dict) or set(body) - set(DEFAULTS):
        raise ValueError('Unknown certificate setting.')
    cfg = {**DEFAULTS, **body}
    if 'dns_provider' not in body and cfg['dns_hook']:
        cfg['dns_provider'] = 'custom'
    certificate_form.active_fields(cfg, DEFAULTS)
    if cfg['dns_provider'] not in ('custom', 'active-directory'):
        raise ValueError('Select Active Directory DNS or an advanced custom hook.')
    ad_dns.normalize_fields(cfg)
    for key in ('enabled', 'automatic', 'accept_terms', 'http_ready', 'test_only', 'internal_ca'):
        if type(cfg[key]) is not bool:
            raise ValueError(key + ' must be true or false.')
    for key in ('directory_url', 'email', 'primary_domain', 'dns_hook', 'credential', 'challenge', 'key_algorithm', 'ad_host'):
        if not isinstance(cfg[key], str) or len(cfg[key]) > 2048 or any(ord(c) < 32 for c in cfg[key]):
            raise ValueError('Invalid value for ' + key + '.')
        cfg[key] = cfg[key].strip()
    cfg['directory_url'] = certificate_form.directory(cfg['directory_url'])
    try:
        url = urlsplit(cfg['directory_url'])
        port = url.port
    except ValueError:
        raise ValueError('Invalid ACME directory URL.') from None
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment or url.query:
        raise ValueError('Use an HTTPS ACME directory URL without credentials, query, or fragment.')
    if cfg['internal_ca'] and not short_names_allowed(cfg):
        raise ValueError("A Let's Encrypt endpoint cannot be treated as an internal CA.")
    allow_short = short_names_allowed(cfg)
    if cfg['email'] and not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', cfg['email']):
        raise ValueError('Enter a valid account email address.')
    if cfg['primary_domain']:
        try:
            cfg['primary_domain'] = domain(cfg['primary_domain'], allow_short=allow_short)
        except ValueError as exc:
            raise ValueError('Primary DNS name: ' + str(exc)) from None
    if not isinstance(cfg['alternative_names'], list) or len(cfg['alternative_names']) > 50:
        raise ValueError('Use at most 50 alternative DNS names.')
    names = []
    for raw in cfg['alternative_names']:
        try:
            name = domain(raw, wildcard=True, allow_short=allow_short)
        except ValueError as exc:
            raise ValueError('Alternative DNS names: ' + str(exc)) from None
        if name != cfg['primary_domain'] and name not in names:
            names.append(name)
    cfg['alternative_names'] = names
    if cfg['challenge'] not in ('dns-01', 'http-01', 'tls-alpn-01'):
        raise ValueError('Select DNS-01, HTTP-01, or TLS-ALPN-01.')
    short_names = [n for n in [cfg['primary_domain'], *cfg['alternative_names']] if n and '.' not in n.removeprefix('*.')]
    if cfg['challenge'] == 'dns-01' and cfg['dns_provider'] == 'active-directory' and short_names:
        raise ValueError('Active Directory DNS-01 requires fully qualified certificate DNS names. The ACME server validates single-label identifiers literally and does not apply the AD DNS search suffix: ' + ', '.join(short_names) + '.')
    if cfg['challenge'] != 'dns-01' and any(n.startswith('*.') for n in names):
        raise ValueError('Wildcard names require DNS-01.')
    if cfg['key_algorithm'] not in ('prime256v1', 'secp384r1', 'rsa'):
        raise ValueError('Select a supported key algorithm.')
    if type(cfg['renew_days']) is not int or not 1 <= cfg['renew_days'] <= 60:
        raise ValueError('Renewal threshold must be between 1 and 60 days.')
    for key in ('dns_hook', 'credential', 'ad_host'):
        if cfg[key] and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', cfg[key]):
            raise ValueError('Select an installed ' + key.replace('_', ' ') + '.')
    if cfg['directory_url'] == STAGING:
        cfg['test_only'] = True
    if cfg['challenge'] != 'dns-01':
        cfg['dns_hook'] = cfg['credential'] = ''
    http01.normalize_fields(cfg, body)
    tlsalpn.normalize_fields(cfg)
    return certificate_form.active_fields(cfg, DEFAULTS)


class Certificates:
    def __init__(self, legacy=None, base=BASE, native=NATIVE):
        self.legacy = legacy or {}
        self.base, self.native = Path(base), Path(native)
        self.settings = self.base / 'config/acme.json'
        self.state = self.base / 'state/acme-job.json'
        self.hooks = self.base / 'config/acme-hooks.d'
        self.webroot = self.base / 'acme/http-01'
        self.module = Path(__file__).resolve()

    def config(self):
        if self.settings.exists():
            return self.bind_inventory(normalize(read_json(self.settings, {})))
        # Read old key/value config without sourcing or executing shell content.
        values = {}
        try:
            for line in self.native.read_text().splitlines():
                if '=' not in line or line.lstrip().startswith('#'):
                    continue
                key, raw = line.split('=', 1)
                try:
                    values[key.strip()] = ' '.join(shlex.split(raw, comments=True))
                except ValueError:
                    continue
        except FileNotFoundError:
            pass
        cfg = dict(DEFAULTS)
        cfg.update(enabled=values.get('ACME_ENABLED') == 'true',
                   directory_url=values.get('CA') or values.get('ACME_CA') or LE,
                   primary_domain=values.get('ACME_PRIMARY_DOMAIN', ''),
                   email=values.get('CONTACT_EMAIL', ''),
                   challenge=values.get('CHALLENGETYPE', 'dns-01'))
        return self.bind_inventory(normalize(cfg))

    def inventory(self):
        path = self.base / 'config/hosts.json'
        if not path.exists() and self.base == BASE:
            path = Path('/etc/mcp-appliance/hosts.json')
        return read_json(path, {'hosts': {}, 'groups': {}})

    def inventory_candidates(self):
        return certificate_form.candidates(self.inventory(), domain)

    def bind_inventory(self, cfg, strict=False):
        if cfg.get('challenge') != 'dns-01' or cfg.get('dns_provider') != 'active-directory':
            return dict(cfg)
        return certificate_form.bind_inventory(cfg, self.inventory(), domain, strict)

    @contextmanager
    def lock(self, wait=False):
        path = self.base / 'state/acme.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            os.chmod(path, 0o600)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                raise ValueError('A certificate operation is already running.') from None
            yield

    def job(self):
        row = read_json(self.state, {'state': 'idle', 'message': 'No certificate request has been run.'})
        if row.get('state') in ('queued', 'running') and time.time() - row.get('updated_at', 0) > 1200:
            row = {**row, 'state': 'interrupted', 'message': 'The previous request did not finish. Check the certificate service log.'}
        return row

    def job_write(self, state, message, action=None):
        row = dict(state=state, message=message, updated_at=int(time.time()))
        if action:
            row['action'] = action
        atomic(self.state, json.dumps(row) + '\n')
        return row

    def busy(self):
        return self.job().get('state') in ('queued', 'running')

    def installed_hooks(self):
        result = []
        if not self.hooks.is_dir():
            return result
        for parent in (self.hooks, *self.hooks.parents):
            st = parent.stat()
            if st.st_uid != 0 or st.st_mode & 0o022 or parent.is_symlink():
                return result
        for path in sorted(self.hooks.iterdir()):
            st = path.lstat()
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', path.name) and stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022 and st.st_mode & 0o100:
                result.append(path.name)
        return result

    def vault(self):
        if not self.legacy.get('vault_status'):
            return {'credentials': [], 'locked': True, 'grants': []}
        return self.legacy['vault_status']()

    def readiness(self, cfg, vault=None):
        cfg = self.bind_inventory(cfg)
        issues, warnings = [], []
        if not os.path.ismount(self.base.parent):
            issues.append('Persistent appliance storage must be mounted.')
        if not shutil.which('dehydrated'):
            issues.append('The dehydrated client is not installed.')
        if not cfg['primary_domain']:
            issues.append('Enter the primary DNS name.')
        if not cfg['email']:
            issues.append('Enter the ACME account email.')
        if not cfg['accept_terms']:
            issues.append('Review and accept the selected certificate authority account terms.')
        if cfg['challenge'] == 'dns-01':
            if cfg['dns_provider'] == 'active-directory':
                if not cfg.get('ad_host') or not cfg.get('ad_server'):
                    issues.append('Select the AD DNS server from Inventory; a Windows host with a full DNS hostname is required.')
                issues.extend(ad_dns.prerequisites(cfg))
            elif not cfg['dns_hook'] or cfg['dns_hook'] not in self.installed_hooks():
                issues.append('Install and select a root-owned DNS challenge hook.')
            if cfg['credential']:
                vault = vault if vault is not None else self.vault()
                cred = next((x for x in vault.get('credentials', []) if x['name'] == cfg['credential']), None)
                if not cred:
                    issues.append('The selected credential is no longer available.')
                else:
                    scopes = cred.get('scopes', [])
                    if (scopes or cfg['dns_provider'] == 'active-directory') and not {'*', 'acme'}.intersection(scopes):
                        issues.append('The selected credential needs the acme scope.')
                    hosts = cred.get('allowed_hosts', [])
                    names = [cfg['ad_server']] if cfg['dns_provider'] == 'active-directory' else [cfg['primary_domain'], *cfg['alternative_names']]
                    if cfg['dns_provider'] == 'active-directory' and cred.get('type') != 'active-directory':
                        issues.append('Choose a credential of type Active Directory.')
                    target_allowed=True
                    if cfg['dns_provider']=='active-directory':
                        inventory_path=self.base/'config/hosts.json'
                        if not inventory_path.exists():inventory_path=Path('/etc/mcp-appliance/hosts.json')
                        try:target_allowed=target_rank(cred,cfg['ad_server'],read_json(inventory_path,{'hosts':{},'groups':{}}))>=0
                        except (OSError,ValueError):target_allowed=False
                    else:target_allowed=not hosts or all(n in hosts for n in names)
                    if not target_allowed:
                        issues.append('The credential must allow the AD DNS server directly or through its inventory group.' if cfg['dns_provider'] == 'active-directory' else 'The credential must allow every certificate DNS name explicitly.')
                    lease = vault.get('lease') or {}
                    allowed = lease.get('expires', 0) > time.time() and bool({'*', 'acme'}.intersection(lease.get('scopes', [])))
                    allowed = allowed or any(g.get('scope') == 'acme' and g.get('credential') == cfg['credential'] and g.get('expires', 0) > time.time() for g in vault.get('grants', []))
                    if not allowed:
                        issues.append('Authorize the credential for acme in Credentials before requesting a certificate.')
                    if cfg['automatic']:
                        warnings.append('Vault credentials require a valid acme lease or grant at renewal time; the vault is never unlocked automatically.')
        elif cfg['challenge'] == 'http-01':
            issues.extend(http01.prerequisites(cfg))
            if cfg['http_mode']=='standalone':
                warnings.append('Only the challenge path is served. The CA must reach TCP 80 for every requested hostname; upstream NAT/proxy routing is not changed.')
        elif cfg['challenge'] == 'tls-alpn-01':
            issues.extend(tlsalpn.prerequisites(cfg))
            warnings.append('The CA must reach TCP 443 with TLS passthrough and acme-tls/1. Existing HTTPS services are not stopped; the management console stays on port 8443.')
        short_names = [n for n in [cfg['primary_domain'], *cfg['alternative_names']] if n and '.' not in n.removeprefix('*.')]
        if short_names:
            warnings.append('Short names are requested literally, not expanded in the certificate. The internal CA and selected challenge method must support literal single-label identifiers: ' + ', '.join(short_names) + '.')
        if cfg['test_only']:
            warnings.append('Test-only mode: issued certificates never replace the management certificate.')
        if not cfg['enabled']:
            warnings.append('ACME is disabled. Saving settings does not issue a certificate.')
        if cfg['challenge'] == 'dns-01' and cfg['dns_provider'] == 'active-directory':
            warnings.append('The selected CA must query this AD DNS view. Public CAs cannot validate records visible only on internal DNS.')
        return {'ready': not issues, 'issues': issues, 'warnings': warnings}

    def provider_readiness(self, cfg):
        if cfg['challenge'] != 'dns-01' or cfg['dns_provider'] != 'active-directory':
            raise ValueError('Select Active Directory DNS before testing the provider.')
        # The read-only connection test needs provider and vault settings, not an ACME account.
        probe = {**cfg, 'enabled': True, 'automatic': False, 'accept_terms': True,
                 'email': 'probe@example.invalid', 'primary_domain': cfg['primary_domain'] or cfg['ad_zone']}
        return self.readiness(probe)

    def certificate(self):
        if self.legacy.get('certificate_health'):
            info = dict(self.legacy['certificate_health']())
        else:
            info = {'present': (self.base / 'identity/web.crt').is_file()}
        if info.get('present'):
            p = command(['/usr/bin/openssl', 'x509', '-in', str(self.base / 'identity/web.crt'), '-noout', '-startdate', '-enddate'])
            dates = dict(line.split('=', 1) for line in p.stdout.splitlines() if '=' in line)
            try:
                info['valid_now'] = p.returncode == 0 and ssl.cert_time_to_seconds(dates['notBefore']) <= time.time() < ssl.cert_time_to_seconds(dates['notAfter'])
            except (KeyError, ValueError):
                info['valid_now'] = False
            info['self_issued'] = bool(info.get('subject')) and info.get('subject') == info.get('issuer')
        info['trust_note'] = 'Validity dates do not establish browser trust or a match to the address you use.'
        return info

    def authorization_status(self):
        cfg=self.config(); vault=self.vault()
        manual=None
        now=int(time.time())
        for grant in vault.get('grants',[]):
            if grant.get('scope')=='acme' and grant.get('credential')==cfg.get('credential') and int(grant.get('expires',0))>now:
                manual={'id':grant.get('id'),'expires':grant.get('expires')}
                break
        automatic=ACMEAuthorization(self.base).status(cfg,self.inventory())
        return {'credential':cfg.get('credential',''),'manual':manual,**automatic}

    def authorize_once(self,actor):
        cfg=self.config()
        if not self.settings.exists(): raise ValueError('Save the ACME configuration before authorizing credential use.')
        if cfg.get('challenge')!='dns-01' or cfg.get('dns_provider')!='active-directory' or not cfg.get('credential'):
            raise ValueError('The saved ACME configuration does not use an Active Directory DNS credential.')
        report=self.readiness(cfg,{**self.vault(),'lease':{'expires':int(time.time())+60,'scopes':['acme']},'grants':[]})
        blocking=[x for x in report['issues'] if 'Authorize the credential' not in x]
        if blocking: raise ValueError(' '.join(blocking))
        p=command(['/usr/bin/mcp-vault-core','grant','acme',cfg['credential'],'300'])
        if p.returncode: raise ValueError('The one-time ACME credential authorization could not be created.')
        result=self.authorization_status()
        result['message']='Credential authorized for one ACME use for up to five minutes. The vault remains locked for other uses.'
        return result

    def authorize_automatic(self,expected_revision,actor):
        cfg=self.config()
        if not self.settings.exists(): raise ValueError('Save the ACME configuration before authorizing automatic renewal.')
        row=ACMEAuthorization(self.base).authorize(cfg,self.inventory(),expected_revision,actor)
        result=self.authorization_status()
        result['message']='Automatic renewal is authorized for this exact saved ACME configuration.'
        return result

    def revoke_automatic(self,actor):
        ACMEAuthorization(self.base).revoke(actor)
        result=self.authorization_status()
        result['message']='Automatic ACME credential authorization revoked.'
        return result

    def status(self):
        cfg, vault = self.config(), self.vault()
        try:
            ad_hosts = self.inventory_candidates()
        except (OSError, ValueError, TypeError):
            ad_hosts = []
        p = command(['/usr/bin/systemctl', 'is-active', 'mcp-acme-update.timer'])
        return dict(config=cfg, certificate=self.certificate(), job=self.job(),
                    settings_saved=self.settings.exists(), appliance_identity=appliance_identity(),
                    ad_inventory_hosts=ad_hosts, challenge_types=certificate_form.CHALLENGES,
                    provider_ready=(self.provider_readiness(cfg)['ready'] if cfg['dns_provider'] == 'active-directory' and cfg['challenge'] == 'dns-01' else False),
                    ad_dns_tools_missing=ad_dns.missing_tools(),
                    readiness=self.readiness(cfg, vault), dns_hooks=self.installed_hooks(),
                    credentials=[self.public_credential(x) for x in vault.get('credentials', [])],
                    vault_locked=vault.get('locked', True), timer_active=p.returncode == 0,
                    schedule='Every 12 hours, with up to 30 minutes of jitter',
                    authorization=self.authorization_status(),
                    http_webroot=str(self.webroot), dns_hook_directory=str(self.hooks))

    def public_credential(self, row):
        result = {key: row.get(key) for key in ('name', 'type', 'scopes', 'allowed_hosts')}
        name = row.get('name', '')
        if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name):
            try:
                meta = read_json(self.base / 'vault/metadata' / (name + '.json'), {})
                if isinstance(meta.get('domain'), str):
                    result['domain'] = domain(meta['domain'])
            except (OSError, ValueError, TypeError):
                pass
        return result

    def render(self, cfg):
        tag = hashlib.sha256((cfg['directory_url'] + str(cfg['test_only'])).encode()).hexdigest()[:16]
        work = self.base / 'acme' / tag
        work.mkdir(parents=True, exist_ok=True)
        os.chmod(work, 0o700)
        self.webroot.mkdir(parents=True, exist_ok=True)
        # Dehydrated appends its SAN to this CSR-only configuration. Do not depend
        # on host policy include files or change HTTPS CA trust verification.
        csr_config = work / 'csr-openssl.cnf'
        atomic(csr_config, '[req]\ndistinguished_name = distinguished_name\n[distinguished_name]\n')
        hook = work / 'managed-hook'
        atomic(hook, '#!/bin/sh\nexec /usr/bin/python3 ' + shlex.quote(str(self.module)) + ' --hook "$@"\n', 0o700)
        names = [cfg['primary_domain'], *cfg['alternative_names']]
        atomic(work / 'domains.txt', ' '.join(n for n in names if n) + '\n')
        values = dict(ACME_ENABLED='true' if cfg['enabled'] else 'false', ACME_PATH=str(work),
                      ACME_PRIMARY_DOMAIN=cfg['primary_domain'], ACME_DOMAINS=' '.join(names),
                      BASEDIR=str(work), DOMAINS_TXT=str(work / 'domains.txt'), CA=cfg['directory_url'],
                      CHALLENGETYPE=cfg['challenge'], HOOK=str(hook), WELLKNOWN=str(self.webroot),
                      CONTACT_EMAIL=cfg['email'], KEY_ALGO=cfg['key_algorithm'], RENEW_DAYS=str(cfg['renew_days']),
                      CERTDIR=str(work / 'certs'), ACCOUNTDIR=str(work / 'accounts'),
                      OPENSSL_CNF=str(csr_config), KEYSIZE='4096', HOOK_CHAIN='no')
        text = '# Generated from persistent config/acme.json; do not edit.\n' + ''.join(k + '=' + shlex.quote(v) + '\n' for k, v in values.items())
        atomic(self.native, text)
        return work

    def save(self, body):
        cfg = self.bind_inventory(normalize(body), strict=True)
        if not os.path.ismount(self.base.parent):
            raise ValueError('Persistent appliance storage must be mounted before saving.')
        with self.lock():
            if self.busy():
                raise ValueError('Wait for the certificate request to finish before saving.')
            # A diagnostic failure after committing settings must not turn
            # a successful write into an apparent rejected save.
            previous_native = self.native.read_bytes() if self.native.exists() else None
            try:
                self.render(cfg)
                atomic(self.settings, json.dumps(cfg, indent=2) + '\n')
            except OSError as exc:
                try:
                    if previous_native is None:
                        self.native.unlink(missing_ok=True)
                    else:
                        atomic(self.native, previous_native)
                except OSError:
                    raise ValueError('Saving failed and the generated ACME configuration could not be restored. Check persistent-storage permissions before retrying.') from exc
                raise ValueError('Certificate settings could not be saved. Check that persistent storage is writable and has free space; your previous configuration was retained.') from exc
            confirmed = read_json(self.settings, None)
            if confirmed != cfg:
                raise ValueError('The saved certificate settings could not be verified. Refresh the saved configuration before requesting a certificate.')
        result = {'ok': True, 'config': confirmed,
                  'message': 'Certificate settings saved. No certificate was requested.'}
        try:
            result['status'] = self.status()
        except Exception:
            result['status'] = None
            result['status_warning'] = 'Settings were saved, but certificate status could not be refreshed. Refresh status before requesting a certificate.'
        return result

    def validate(self, body):
        return self.readiness(self.bind_inventory(normalize(body), strict=True))

    def action(self, body):
        action = body.get('action')
        if action not in ('issue', 'renew', 'force', 'test-provider'):
            raise ValueError('Unknown certificate action.')
        if action == 'force' and body.get('confirm_force') is not True:
            raise ValueError('Confirm force renewal; CA rate limits may apply.')
        with self.lock():
            if self.busy():
                raise ValueError('A certificate request is already queued or running.')
            cfg = self.config()
            if action != 'test-provider' and not cfg['enabled']:
                raise ValueError('Enable ACME and save the settings first.')
            if action == 'scheduled' and cfg.get('credential'):
                service = ACMEAuthorization(self.base).status(cfg,self.inventory()).get('automatic_authorized') is True
                vault = self.vault()
                if service:
                    vault = {**vault,'lease':{'expires':int(time.time())+60,'scopes':['acme']}}
                report = self.readiness(cfg,vault)
            else:
                report = self.provider_readiness(cfg) if action == 'test-provider' else self.readiness(cfg)
            if report['issues']:
                raise ValueError(' '.join(report['issues']))
            self.job_write('queued', 'Certificate request queued.', action)
            p = command(['/usr/bin/systemd-run', '--quiet', '--collect', '--no-block',
                         '--unit=mcp-acme-request', '--property=Type=oneshot',
                         '--property=UMask=0077', '--property=TimeoutStartSec=15min',
                         '/usr/bin/python3', str(self.module), '--run', action])
            if p.returncode:
                self.job_write('failed', 'Could not start the certificate service.', action)
                raise ValueError('Could not start the certificate service. Check the system journal.')
        return {'ok': True, 'message': 'Request started. This page will update as it runs.', 'job': self.job()}

    def run(self, action):
        with self.lock(wait=action != 'scheduled'):
            cfg = self.config()
            if action != 'test-provider' and (not cfg['enabled'] or action == 'scheduled' and not cfg['automatic']):
                return 0
            self.job_write('running', 'Checking certificate prerequisites.', action)
            if cfg['credential']:
                self.legacy['vault_status'] = lambda: json.loads(command(['/usr/bin/mcp-vault-core', 'status']).stdout)
            report = self.provider_readiness(cfg) if action == 'test-provider' else self.readiness(cfg)
            if report['issues']:
                self.job_write('failed', ' '.join(report['issues']), action)
                return 1
            self.render(cfg)
            stage = Path(tempfile.mkdtemp(prefix='acme-stage-', dir=self.base / 'state'))
            os.chmod(stage, 0o700)
            env = os.environ.copy()
            env.update(MCP_ACME_STAGE=str(stage))
            log = self.base / 'log/acme-last.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.job_write('running', 'Testing AD authentication and DNS zone access.' if action == 'test-provider' else 'Registering the account and checking or issuing the certificate.', action)
                argv = ['/usr/bin/python3', str(self.module), '--client', action]
                if cfg['credential']:
                    argv = ['/usr/bin/mcp-vault-run', 'acme', cfg['credential'], 'ACME_CREDENTIAL_FILE', '--', *argv]
                with log.open('w') as output:
                    os.chmod(log, 0o600)
                    p = subprocess.run(argv, stdout=output, stderr=subprocess.STDOUT, env=env, timeout=840)
                if p.returncode:
                    self.job_write('failed', 'ACME request failed. The current certificate is unchanged. See the root-only ACME log.', action)
                    return 1
                if action == 'test-provider':
                    message = 'AD authentication, DNS service ticket and authoritative zone query passed. No DNS records were changed; write permissions are not yet proven.'
                elif (stage / 'web.crt').exists():
                    if cfg['test_only']:
                        message = 'Test issuance succeeded. The management certificate was not changed.'
                    else:
                        self.install_pair(stage)
                        message = 'Certificate issued and installed. The management web service was reloaded.'
                else:
                    message = 'Renewal check succeeded. No replacement certificate was needed.'
                self.job_write('succeeded', message, action)
                return 0
            except (OSError, subprocess.SubprocessError, ValueError):
                self.job_write('failed', 'Certificate operation failed or timed out. Check the root-only ACME log and web service.', action)
                return 1
            finally:
                if list(stage.glob('ad-dns-*.json')):
                    # Preserve exact pending TXT cleanup records for an administrator.
                    stage.rename(stage.with_name(stage.name.replace('acme-stage-', 'acme-needs-cleanup-', 1)))
                else:
                    shutil.rmtree(stage, ignore_errors=True)

    def stage_context(self):
        stage = Path(os.environ.get('MCP_ACME_STAGE', ''))
        if stage.is_symlink() or not stage.is_dir() or stage.parent != self.base / 'state' or not stage.name.startswith('acme-stage-'):
            raise ValueError('Certificate staging context is missing.')
        return stage

    @staticmethod
    def ad_credential():
        # mcp-vault-run provides a short-lived, already-authorized secret file.
        path = Path(os.environ.get('ACME_CREDENTIAL_FILE', ''))
        try:
            path.resolve(strict=True).relative_to('/run/mcp-appliance/vault')
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                st = os.fstat(stream.fileno())
                if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077 or st.st_size > 16384:
                    raise ValueError('Invalid vault file.')
                value = json.load(stream)
            return value
        except (OSError, ValueError):
            raise ValueError('An authorized Active Directory vault credential is required.') from None

    def client(self, action):
        cfg = self.config()
        def dehydrated(env=None):
            if not cfg['accept_terms']:
                return 1
            common = ['dehydrated', '--config', str(self.native)]
            if cfg['challenge'] == 'tls-alpn-01':
                common += ['--alpn', str(self.stage_context() / 'alpn-generated')]
            if subprocess.run([*common, '--register', '--accept-terms'], env=env, timeout=120).returncode:
                return 1
            return subprocess.run([*common, '--cron', *(['--force'] if action == 'force' else [])], env=env, timeout=650).returncode
        if cfg['challenge'] == 'dns-01' and cfg['dns_provider'] == 'active-directory':
            stage = self.stage_context()
            with ad_dns.kerberos(cfg, self.ad_credential()) as env:
                provider = ad_dns.ADDNS(cfg, env)
                try:
                    if action == 'test-provider':
                        provider.check_zone()
                        return 0
                    return dehydrated(env)
                finally:
                    provider.cleanup(stage)
        if action == 'test-provider':
            raise ValueError('Select Active Directory DNS before testing.')
        if cfg['challenge'] == 'tls-alpn-01':
            with tlsalpn.Responder(cfg, self.stage_context()):
                return dehydrated()
        if cfg['challenge']=='http-01' and cfg['http_mode']=='standalone':
            with http01.Responder(cfg, self.stage_context()):
                return dehydrated()
        return dehydrated()

    def hook(self, args):
        event = args[0] if args else ''
        cfg = self.config()
        if event in ('deploy_challenge', 'clean_challenge') and cfg['challenge'] == 'tls-alpn-01':
            if len(args) != 4:
                raise ValueError('Unexpected TLS challenge arguments.')
            tlsalpn.publish(self.stage_context(), cfg, event, args[1], args[2], args[3])
            return 0
        if event in ('deploy_challenge', 'clean_challenge') and cfg['challenge']=='http-01':
            if cfg['http_mode']=='standalone':
                if len(args)!=4: raise ValueError('Unexpected HTTP challenge arguments.')
                http01.publish(self.stage_context(), cfg, event, args[1], args[2], args[3])
            return 0
        if event in ('deploy_challenge', 'clean_challenge') and cfg['challenge'] == 'dns-01':
            if cfg['dns_provider'] == 'active-directory':
                if len(args) != 4:
                    raise ValueError('Unexpected AD DNS hook arguments.')
                return ad_dns.ADDNS(cfg).hook(event, args[1], args[3], self.stage_context())
            if cfg['dns_hook'] not in self.installed_hooks():
                raise ValueError('The configured DNS hook is unavailable or unsafe.')
            return subprocess.run([str(self.hooks / cfg['dns_hook']), *args], timeout=180).returncode
        if event == 'deploy_cert':
            if len(args) < 5 or args[1] != cfg['primary_domain']:
                raise ValueError('Unexpected certificate deployment.')
            stage = Path(os.environ.get('MCP_ACME_STAGE', ''))
            if not stage.is_dir() or stage.parent != self.base / 'state' or not stage.name.startswith('acme-stage-'):
                raise ValueError('Certificate staging context is missing.')
            key, chain = Path(args[2]), Path(args[4])
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(chain), str(key))
            p = command(['/usr/bin/openssl', 'x509', '-in', str(chain), '-noout', '-startdate', '-enddate'])
            dates = dict(line.split('=', 1) for line in p.stdout.splitlines() if '=' in line)
            if p.returncode or not ssl.cert_time_to_seconds(dates['notBefore']) <= time.time() < ssl.cert_time_to_seconds(dates['notAfter']):
                raise ValueError('The issued certificate is not currently valid.')
            # Check the issued SAN set, not the display-oriented x509 -checkhost
            # command's exit status (which is not portable across OpenSSL versions).
            # Exact identifiers also ensure a requested wildcard was actually issued.
            p = command(['/usr/bin/openssl', 'x509', '-in', str(chain), '-noout', '-ext', 'subjectAltName'])
            issued = {domain(n, wildcard=True, allow_short=short_names_allowed(cfg)) for n in re.findall(r'DNS:([^,\s]+)', p.stdout)}
            expected = {cfg['primary_domain'], *cfg['alternative_names']}
            if p.returncode or issued != expected:
                raise ValueError('The issued certificate DNS names do not match the requested names.')
            atomic(stage / 'web.key', key.read_bytes())
            atomic(stage / 'web.crt', chain.read_bytes(), 0o644)
        return 0

    def install_pair(self, stage):
        identity = self.base / 'identity'
        old = {name: (identity / name).read_bytes() for name in ('web.key', 'web.crt')}
        try:
            for name, mode in (('web.key', 0o600), ('web.crt', 0o644)):
                atomic(identity / name, (stage / name).read_bytes(), mode)
            if command(['/usr/bin/systemctl', 'restart', 'mcp-appliance-web.service']).returncode:
                raise ValueError('Web service reload failed.')
            self.check_web(identity / 'web.crt')
        except Exception:
            for name, data in old.items():
                atomic(identity / name, data, 0o600 if name.endswith('key') else 0o644)
            command(['/usr/bin/systemctl', 'restart', 'mcp-appliance-web.service'])
            raise

    @staticmethod
    def check_web(cert):
        # Loopback probe trusts this exact local identity as an anchor.
        context = ssl.create_default_context(cafile=str(cert))
        context.check_hostname = False
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        for _ in range(8):
            conn = http.client.HTTPSConnection('127.0.0.1', 8443, context=context, timeout=3)
            try:
                conn.request('GET', '/api/registration')
                if conn.getresponse().status == 200:
                    return
            except OSError:
                pass
            finally:
                conn.close()
            time.sleep(0.5)
        raise ValueError('The management web service did not return healthy.')


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--run', choices=['issue', 'renew', 'force', 'scheduled', 'test-provider'])
    group.add_argument('--client', choices=['issue', 'renew', 'force', 'scheduled', 'test-provider'])
    group.add_argument('--hook', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    manager = Certificates()
    try:
        return manager.run(args.run) if args.run else manager.client(args.client) if args.client else manager.hook(args.hook)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print('Certificate operation failed. Review the certificate configuration and service log.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
