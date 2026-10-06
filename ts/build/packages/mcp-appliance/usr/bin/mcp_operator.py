"""Operator-facing MCP metadata, independent client access and bounded probes.

Only metadata is stored here. Target-system credentials remain in the vault.
Client tokens are returned once and only SHA-256 digests are persisted.
"""
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time


class OperatorAPI:
    def __init__(self, legacy):
        self.legacy = legacy
        self.base = Path(legacy['BASE'])
        self.clients_file = self.base / 'config/ai-connections.json'
        self.events_file = self.base / 'log/ai-connections.json'
        self.lock = threading.RLock()
        self.probe_lock = threading.Lock()
        self.last_probe = None
        self.last_probe_mono = 0
        self.last_probe_runtime = None

    @staticmethod
    def _load(path, default):
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return default
        # Corrupt access state must fail closed, not become an empty registry.

    def _write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(value, stream, ensure_ascii=True)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _clients(self):
        doc = self._load(self.clients_file, {'version': 1, 'clients': []})
        if not isinstance(doc, dict) or not isinstance(doc.get('clients'), list):
            raise ValueError('Connection registry is invalid; restore its configuration before changing access.')
        return doc

    @staticmethod
    def _public(row):
        return {key: row.get(key) for key in
                ('id', 'name', 'application', 'method', 'created', 'revoked_at',
                 'last_request_at', 'last_http_status')}

    def _event(self, kind, name, detail):
        with self.lock:
            rows = self._load(self.events_file, [])
            if not isinstance(rows, list):
                rows = []
            rows.append({'time': int(time.time()), 'kind': kind, 'name': name, 'detail': detail})
            self._write(self.events_file, rows[-150:])

    def connections(self):
        with self.lock:
            doc = self._clients()
            legacy = self.legacy['connection_info']()
            events = self._load(self.events_file, [])
            return {
                'url': legacy['url'], 'transport': 'streamable-http',
                'clients': [self._public(row) for row in doc['clients']],
                'shared_access': {'enabled': bool(legacy.get('token')), 'individual_revocation': False},
                'permissions': 'All tools exposed by the active MCP; target credentials and vault rules still apply.',
                'per_client_permissions': False,
                'remote_configuration': 'not_managed',
                'events': list(reversed(events[-40:])) if isinstance(events, list) else [],
            }

    def create_connection(self, body):
        name = str(body.get('name', '')).strip()
        application = str(body.get('application', 'generic')).strip()
        if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise ValueError('Enter a connection name of 1 to 100 characters.')
        if application not in ('generic', 'vscode', 'cursor', 'local-agent'):
            raise ValueError('This setup flow currently provisions direct HTTP clients only.')
        if body.get('method', 'direct') != 'direct':
            raise ValueError('A private tunnel or public gateway must be configured separately.')
        if body.get('confirm_full_access') is not True:
            raise ValueError('Confirm the actual access granted to this application.')
        if not os.path.ismount('/var/prstnt'):
            raise ValueError('Provision persistent storage before creating client access.')
        with self.lock:
            doc = self._clients()
            if len(doc['clients']) >= 200:
                raise ValueError('Connection limit reached.')
            if any(r['name'].casefold() == name.casefold() and not r.get('revoked_at') for r in doc['clients']):
                raise ValueError('An enabled connection already uses this name.')
            identifier = secrets.token_hex(8)
            token = 'mcp_' + identifier + '_' + secrets.token_urlsafe(32)
            row = {'id': identifier, 'name': name, 'application': application, 'method': 'direct',
                   'created': int(time.time()), 'revoked_at': None, 'last_request_at': None,
                   'last_http_status': None, 'token_hash': hashlib.sha256(token.encode()).hexdigest()}
            doc['clients'].append(row)
            self._write(self.clients_file, doc)
            self._event('access-created', name, 'Independent client token issued with full MCP access.')
            return {'ok': True, 'connection': self._public(row), 'token': token}

    def revoke_connection(self, body):
        identifier = str(body.get('id', ''))
        if not re.fullmatch(r'[0-9a-f]{16}', identifier):
            raise ValueError('Select a valid connection.')
        with self.lock:
            doc = self._clients()
            row = next((r for r in doc['clients'] if r['id'] == identifier), None)
            if row is None:
                raise ValueError('Connection not found.')
            if not row.get('revoked_at'):
                row['revoked_at'] = int(time.time())
                row['token_hash'] = ''
                self._write(self.clients_file, doc)
                self._event('access-revoked', row['name'], 'New requests are blocked. An already-running request may finish.')
            return {'ok': True}

    def authenticate_client(self, authorization):
        if not authorization.startswith('Bearer mcp_') or len(authorization) > 256:
            return None
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        try:
            with self.lock:
                for row in self._clients()['clients']:
                    if not row.get('revoked_at') and hmac.compare_digest(str(row.get('token_hash', '')), digest):
                        return row['id']
        except (OSError, ValueError, KeyError):
            return None
        return None

    def record_gateway_request(self, identifier, status):
        # Deliberately do not record payloads, target secrets, headers, or tokens.
        try:
            with self.lock:
                doc = self._clients()
                row = next((r for r in doc['clients'] if r['id'] == identifier), None)
                if row is None:
                    return
                before = row.get('last_http_status')
                first = not row.get('last_request_at')
                now = int(time.time())
                # Bound disk writes on a busy streaming gateway.
                if not first and before == status and now - row['last_request_at'] < 15:
                    return
                row['last_request_at'] = now
                row['last_http_status'] = status
                self._write(self.clients_file, doc)
                if first or (before is not None and (before < 400) != (status < 400)):
                    self._event('gateway-request', row['name'], 'Authenticated gateway request returned HTTP ' + str(status) + '. This is not a tool-result check.')
        except (OSError, ValueError):
            pass  # Telemetry cannot break an authorized MCP request.

    @staticmethod
    def version_metadata(generation, manifest=None):
        manifest = manifest or {}
        match = re.fullmatch(r'(.+)-build-([0-9]+)', str(generation or ''))
        number = manifest.get('build_number')
        if not isinstance(number, int) or isinstance(number, bool):
            number = int(match[2]) if match else None
        return {'generation': generation, 'version': ('Build ' + str(number)) if number is not None else str(manifest.get('version') or generation or 'Not selected'),
                'build_number': number, 'family': match[1] if match else None,
                'source_sha': str(manifest.get('source_sha') or ''), 'source': str(manifest.get('source') or '')}

    def runtime(self):
        state = self.legacy['status']()
        generations = self.legacy['generation_status']()
        versions = []
        root = self.base / 'mcp/generations'
        for gen in generations.get('generations', []):
            if not isinstance(gen, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', gen):
                continue
            path = root / gen / 'manifest.json'
            try:
                path.resolve().relative_to(root.resolve())
                manifest = self._load(path, {})
                if not isinstance(manifest, dict):
                    manifest = {}
            except (OSError, ValueError):
                manifest = {}
            versions.append(self.version_metadata(gen, manifest))
        inventory = self._load(self.legacy['FILES']['hosts'], {'hosts': {}, 'groups': {}})
        vault = self.legacy['vault_status']()
        selected = state.get('mcp_selected') or {}
        runtime_key = (state.get('mcp_service'), state.get('mcp_runtime'))
        probe = self.last_probe if runtime_key == self.last_probe_runtime else None
        return {'timestamp': int(time.time()), 'service': state.get('mcp_service', 'unknown'),
                'runtime': state.get('mcp_runtime', ''), 'selected': selected,
                'active': generations.get('active'), 'previous': generations.get('previous'),
                'versions': versions, 'quarantined': state.get('mcp_quarantined', []),
                'probe': probe, 'host_count': len(inventory.get('hosts', {})),
                'group_count': len(inventory.get('groups', {})),
                'credential_count': len(vault.get('credentials', [])),
                'vault_locked': vault.get('locked'), 'vault_available': vault.get('available', False)}

    def probe(self):
        # Fixed loopback destination: user input can never turn this into SSRF.
        # No tools/call requests are sent by this test.
        with self.probe_lock:
            state = self.legacy['status']()
            runtime_key = (state.get('mcp_service'), state.get('mcp_runtime'))
            if self.last_probe and runtime_key == self.last_probe_runtime and time.monotonic() - self.last_probe_mono < 5:
                return self.last_probe
            result = {'checked_at': int(time.time()), 'responding': False, 'tools': [],
                      'scope': 'Appliance to local MCP only; client reachability, gateway authentication and client TLS trust are not tested.'}
            session = None
            version = '2025-03-26'
            started = time.monotonic()

            def request(method, params=None, rid=None, verb='POST'):
                connection = http.client.HTTPConnection('127.0.0.1', 8000, timeout=5)
                headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                           'MCP-Protocol-Version': version}
                if session:
                    headers['Mcp-Session-Id'] = session
                message = {'jsonrpc': '2.0', 'method': method}
                if params is not None:
                    message['params'] = params
                if rid is not None:
                    message['id'] = rid
                try:
                    connection.request(verb, '/mcp', json.dumps(message) if verb == 'POST' else None, headers)
                    response = connection.getresponse()
                    sid = response.getheader('Mcp-Session-Id')
                    if not 200 <= response.status < 300:
                        raise ValueError('Local MCP returned HTTP ' + str(response.status))
                    if rid is None:
                        return {}, sid
                    if 'text/event-stream' in (response.getheader('Content-Type') or ''):
                        total = 0
                        data = []
                        while total < 4 * 1024 * 1024 and time.monotonic() - started < 15:
                            line = response.readline(65536)
                            if not line:
                                break
                            total += len(line)
                            if line.startswith(b'data:'):
                                data.append(line[5:].strip())
                            elif not line.strip() and data:
                                payload = json.loads(b'\n'.join(data))
                                if payload.get('id') == rid:
                                    break
                                data = []
                        else:
                            raise ValueError('MCP test response exceeded its limit.')
                        if not data:
                            raise ValueError('No MCP response received.')
                        payload = json.loads(b'\n'.join(data))
                    else:
                        raw = response.read(4 * 1024 * 1024 + 1)
                        if len(raw) > 4 * 1024 * 1024:
                            raise ValueError('MCP test response exceeded its limit.')
                        payload = json.loads(raw)
                    if payload.get('jsonrpc') != '2.0' or payload.get('id') != rid or 'error' in payload:
                        raise ValueError('MCP protocol check failed.')
                    if not isinstance(payload.get('result'), dict):
                        raise ValueError('Invalid MCP result.')
                    return payload['result'], sid
                finally:
                    connection.close()
            try:
                if state.get('mcp_service') != 'active':
                    raise ValueError('Runtime service is not running.')
                init, session = request('initialize', {'protocolVersion': version, 'capabilities': {}, 'clientInfo': {'name': 'ThinStation operator check', 'version': '1'}}, 1)
                version = init.get('protocolVersion') or version
                request('notifications/initialized')
                result.update({'responding': True, 'server_name': str(init.get('serverInfo', {}).get('name') or 'MCP service'), 'protocol_version': version})
                if 'tools' in init.get('capabilities', {}):
                    cursor = None
                    seen = set()
                    for page in range(5):
                        if time.monotonic() - started > 15:
                            result['tools_truncated'] = True
                            break
                        listing, _ = request('tools/list', {'cursor': cursor} if cursor else {}, page + 2)
                        for item in listing.get('tools', []):
                            if isinstance(item, dict):
                                result['tools'].append({'name': str(item.get('name') or '')[:200], 'description': str(item.get('description') or '')[:600]})
                        cursor = listing.get('nextCursor')
                        if len(result['tools']) > 1000:
                            result['tools'] = result['tools'][:1000]
                            result['tools_truncated'] = True
                            break
                        if not cursor:
                            break
                        if cursor in seen:
                            raise ValueError('MCP returned a repeated capability cursor.')
                        seen.add(cursor)
                    else:
                        result['tools_truncated'] = bool(cursor)
                result['message'] = 'MCP handshake succeeded; no tools were executed.'
            except Exception as exc:
                result['error'] = str(exc)[:300]
                if result.get('responding'):
                    result['message'] = 'MCP responds, but the capability list could not be completed.'
            finally:
                if session:
                    try:
                        request('', verb='DELETE')
                    except Exception:
                        pass
            self.last_probe = result
            self.last_probe_runtime = runtime_key
            self.last_probe_mono = time.monotonic()
            return result
