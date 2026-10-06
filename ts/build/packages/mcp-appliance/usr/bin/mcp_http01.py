"""Temporary token-only HTTP-01 responder; no management API or file serving."""
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time

PREFIX = '/.well-known/acme-challenge/'
TOKEN = re.compile(r'[A-Za-z0-9_-]{22,256}')
MAX_AGE = 900


def normalize_fields(cfg, supplied):
    if 'http_mode' not in supplied and supplied.get('challenge') == 'http-01' and supplied.get('http_ready'):
        cfg['http_mode'] = 'external'
    if cfg['http_mode'] not in ('standalone', 'external'):
        raise ValueError('Select the appliance HTTP responder or an external webroot.')
    if type(cfg['http_public_access']) is not bool:
        raise ValueError('HTTP public access must be true or false.')
    networks = cfg['http_source_networks']
    if not isinstance(networks, list) or len(networks) > 32:
        raise ValueError('Use at most 32 HTTP validation source addresses or networks.')
    clean = []
    for value in networks:
        if not isinstance(value, str):
            raise ValueError('HTTP validation sources must be IP addresses or CIDR networks.')
        try:
            network = ipaddress.ip_network(value.strip(), strict=False)
        except ValueError:
            raise ValueError('HTTP validation sources must be IP addresses or CIDR networks.') from None
        if network.prefixlen == 0:
            raise ValueError('Use the explicit public-access option instead of a /0 network.')
        if str(network) not in clean:
            clean.append(str(network))
    cfg['http_source_networks'] = clean
    return cfg


def prerequisites(cfg):
    issues = []
    if not cfg['http_ready']:
        issues.append('Authorize the temporary HTTP listener and confirm that the CA can reach this appliance on TCP 80.' if cfg['http_mode'] == 'standalone' else 'Confirm the external HTTP challenge route on TCP 80 for every certificate name.')
    if cfg['http_mode'] == 'standalone':
        if not cfg['http_public_access'] and not cfg['http_source_networks']:
            issues.append('Specify the internal CA validation source IP/network, or explicitly allow public validation.')
        if not shutil.which('nft'):
            issues.append('The nftables client is required for the appliance HTTP responder.')
    return issues


def entry(root, host, token):
    return Path(root) / (hashlib.sha256((host + '\0' + token).encode()).hexdigest() + '.json')


def publish(stage, cfg, event, name, token, value):
    if name not in {cfg['primary_domain'], *cfg['alternative_names']} or not TOKEN.fullmatch(token):
        raise ValueError('HTTP challenge does not belong to the saved certificate order.')
    if not re.fullmatch(re.escape(token) + r'\.[A-Za-z0-9_-]{43}', value):
        raise ValueError('Invalid HTTP challenge key authorization.')
    root = Path(stage) / 'http-tokens'
    if root.is_symlink() or not root.is_dir():
        raise ValueError('The HTTP responder is not active for this request.')
    path = entry(root, name, token)
    if event == 'clean_challenge':
        path.unlink(missing_ok=True)
        return
    if event != 'deploy_challenge':
        raise ValueError('Unexpected HTTP challenge event.')
    fd, temporary = tempfile.mkstemp(prefix='.token-', dir=root)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump({'host': name, 'token': token, 'value': value, 'expires': time.time() + MAX_AGE}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Handler(BaseHTTPRequestHandler):
    server_version = 'ACME-Challenge'
    sys_version = ''
    protocol_version = 'HTTP/1.0'

    def setup(self):
        self.request.settimeout(3)
        super().setup()

    def log_message(self, *args):
        pass

    def response(self, code, body=b''):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=ascii')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Length', '0') != '0':
            self.response(400)
            return
        hosts = self.headers.get_all('Host', [])
        if len(hosts) != 1:
            self.response(400)
            return
        host = hosts[0].lower()
        if host.endswith(':80'):
            host = host[:-3]
        host = host.rstrip('.')
        token = self.path[len(PREFIX):] if self.path.startswith(PREFIX) else ''
        if host not in self.server.names or not TOKEN.fullmatch(token):
            self.response(404)
            return
        try:
            fd = os.open(entry(self.server.root, host, token), os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as stream:
                st = os.fstat(stream.fileno())
                if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077 or st.st_nlink != 1 or st.st_size > 2048:
                    raise ValueError('Invalid challenge entry.')
                row = json.load(stream)
            if row['host'] != host or row['token'] != token or not time.time() < row['expires'] <= time.time() + MAX_AGE + 5:
                raise ValueError('Inactive challenge.')
            value = row['value']
            if not re.fullmatch(re.escape(token) + r'\.[A-Za-z0-9_-]{43}', value):
                raise ValueError('Invalid key authorization.')
            self.response(200, value.encode('ascii'))
        except (OSError, ValueError, KeyError, TypeError):
            self.response(404)

    do_HEAD = do_GET

    def do_POST(self):
        self.response(405)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
    do_CONNECT = do_POST
    do_TRACE = do_POST


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, address, family, root, names):
        self.address_family = family
        self.slots = threading.BoundedSemaphore(16)
        self.names = frozenset(names)
        self.root = Path(root)
        try:
            super().__init__(address, Handler, bind_and_activate=False)
            if family == socket.AF_INET6:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            self.server_bind()
            self.server_activate()
        except BaseException:
            self.server_close()
            raise

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass


class Firewall:
    def __init__(self, cfg, port=80, prefix="mcp-http01"):
        if port not in (80, 443) or prefix not in ("mcp-http01", "mcp-alpn01"):
            raise ValueError("Unsupported challenge firewall policy.")
        self.port = port
        self.cfg = cfg
        self.tag = prefix + '-' + secrets.token_hex(6)
        self.set_name = self.tag.replace('-', '_')
        self.active = False

    def command(self, args, text=None):
        return subprocess.run([shutil.which('nft') or '/usr/bin/nft', *args], input=text, text=True, capture_output=True, timeout=10)

    def open(self):
        if self.command(['list', 'chain', 'inet', 'mcp_appliance', 'input']).returncode:
            raise ValueError('The appliance firewall is unavailable. Use an external webroot or restore its nftables input chain.')
        lines = [f'add set inet mcp_appliance {self.set_name} {{ type inet_service; flags timeout; }}',
                 f'add element inet mcp_appliance {self.set_name} {{ {self.port} timeout {MAX_AGE}s }}']
        if self.cfg['http_public_access']:
            lines.append(f'insert rule inet mcp_appliance input tcp dport @{self.set_name} counter accept comment "{self.tag}"')
        else:
            for version, family in ((4, 'ip'), (6, 'ip6')):
                sources = [str(ipaddress.ip_network(n)) for n in self.cfg['http_source_networks'] if ipaddress.ip_network(n).version == version]
                if sources:
                    lines.append(f'insert rule inet mcp_appliance input {family} saddr {{ ' + ', '.join(sources) + f' }} tcp dport @{self.set_name} counter accept comment "{self.tag}"')
        if self.command(['-f', '-'], '\n'.join(lines) + '\n').returncode:
            raise ValueError('Could not install the temporary HTTP challenge firewall allowance.')
        self.active = True

    def close(self):
        if not self.active:
            return
        result = self.command(['-j', '-a', 'list', 'chain', 'inet', 'mcp_appliance', 'input'])
        if result.returncode:
            raise ValueError('Could not inspect HTTP firewall cleanup; its access set expires automatically.')
        lines = []
        for item in json.loads(result.stdout).get('nftables', []):
            rule = item.get('rule', {})
            if rule.get('comment') == self.tag:
                lines.append('delete rule inet mcp_appliance input handle ' + str(int(rule['handle'])))
        lines.append('delete set inet mcp_appliance ' + self.set_name)
        if self.command(['-f', '-'], '\n'.join(lines) + '\n').returncode:
            raise ValueError('HTTP listener stopped, but firewall cleanup failed; its access set expires automatically.')
        self.active = False


class Responder(AbstractContextManager):
    def __init__(self, cfg, stage):
        self.cfg = cfg
        self.root = Path(stage) / 'http-tokens'
        self.servers = []
        self.threads = []
        self.firewall = Firewall(cfg)

    def __enter__(self):
        issues = prerequisites(self.cfg)
        if issues:
            raise ValueError(' '.join(issues))
        if self.root.exists() or self.root.is_symlink():
            raise ValueError('HTTP challenge workspace is already in use.')
        self.root.mkdir(mode=0o700)
        names = [self.cfg['primary_domain'], *self.cfg['alternative_names']]
        try:
            try:
                self.servers.append(Server(('0.0.0.0', 80), socket.AF_INET, self.root, names))
                if socket.has_ipv6 and Path('/proc/net/if_inet6').exists():
                    self.servers.append(Server(('::', 80), socket.AF_INET6, self.root, names))
            except OSError:
                raise ValueError('TCP 80 is unavailable. Stop the conflicting service or select an external webroot.') from None
            self.firewall.open()
            for server in self.servers:
                thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
                thread.start()
                self.threads.append(thread)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        for index, server in enumerate(self.servers):
            if index < len(self.threads):
                server.shutdown()
            server.server_close()
        self.servers.clear()
        for thread in self.threads:
            thread.join(timeout=4)
        self.threads.clear()
        try:
            self.firewall.close()
        finally:
            if self.root.is_dir():
                shutil.rmtree(self.root)
        return False
