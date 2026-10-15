"""Runtime selection for persistent updates, an immutable baseline, and rescue."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

BASE = Path('/var/prstnt/mcp-appliance')
RUN = Path('/run/mcp-appliance')
BUNDLE = Path('/usr/lib64/mcp-fallback')
CHECKER = Path('/usr/bin/mcp-selftest')


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write('\n')
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def valid_name(name):
    return isinstance(name, str) and name not in ('', '.', '..') and all(
        c.isascii() and (c.isalnum() or c in '._-') for c in name)


def validate_generation(path, kind='persistent', checker=CHECKER):
    """Validate code and native imports without starting a listening service."""
    path = Path(path).resolve()
    try:
        data = json.loads((path / 'manifest.json').read_text())
        if not isinstance(data, dict):
            raise ValueError('manifest must be an object')
        name = data.get('name') or path.name
        if not valid_name(name):
            raise ValueError('invalid generation name')
        command = data.get('command', '')
        if not isinstance(command, str) or not command.strip():
            raise ValueError('command missing')
        argv = shlex.split(command)
        if not argv:
            raise ValueError('command missing')
        exe = Path(argv[0])
        if not exe.is_absolute():
            exe = path / exe
        if not exe.is_file() or not os.access(exe, os.X_OK):
            raise ValueError('executable missing: ' + str(exe))
        hashes = data.get('sha256', {})
        if not isinstance(hashes, dict):
            raise ValueError('invalid manifest hashes')
        for rel, expected in hashes.items():
            target = (path / rel).resolve()
            target.relative_to(path)
            with target.open('rb') as stream:
                got = hashlib.file_digest(stream, 'sha256').hexdigest()
            if got != str(expected).lower():
                raise ValueError('hash mismatch: ' + rel)
        full = (path / 'app/server.py').is_file() and (path / '.venv/bin/python').is_file()
        if full:
            result = subprocess.run([str(checker), 'imports', str(path)],
                                    text=True, capture_output=True, timeout=30)
        else:
            test = data.get('self_test', '')
            result = subprocess.run(test, shell=True, cwd=path, text=True,
                                    capture_output=True, timeout=20) if test else None
        if result is not None and result.returncode:
            detail = (result.stderr or result.stdout).strip()[-1800:]
            raise ValueError('runtime preflight failed: ' + detail)
        wd = Path(data.get('working_directory', '.'))
        if not wd.is_absolute():
            wd = path / wd
        if not wd.is_dir():
            raise ValueError('working directory missing')
        selected = {'kind': kind, 'generation': name, 'command': shlex.join([str(exe), *argv[1:]]),
                    'working_directory': str(wd.resolve()), 'full_runtime': full,
                    'version': str(data.get('version') or name),
                    'build_number': data.get('build_number'),
                    'source_sha': str(data.get('source_sha') or '')}
        return True, 'ok', selected
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        return False, str(exc), None


class Selector:
    def __init__(self, base=BASE, run=RUN, bundle=BUNDLE, checker=CHECKER,
                 rescue='/usr/bin/mcp-recovery'):
        self.base, self.run, self.bundle = Path(base), Path(run), Path(bundle)
        self.checker, self.rescue = Path(checker), rescue
        self.failed_file = self.base / 'state/mcp-failed-generations.json'
        self.bundle_failed_file = self.run / 'bundled-failure.json'

    def resolve_slot(self, name):
        try:
            root = (self.base / 'mcp/generations').resolve(strict=True)
            path = (self.base / 'mcp' / name).resolve(strict=True)
            path.relative_to(root)
            return path if path.is_dir() and path != root else None
        except (OSError, ValueError, RuntimeError):
            return None

    def bundle_identity(self):
        receipt = read_json(self.bundle / 'bundled.json', {})
        sha = receipt.get('archive_sha256', '') if isinstance(receipt, dict) else ''
        return sha if isinstance(sha, str) and len(sha) == 64 else None

    def choose(self):
        attempts = []
        failure_state = read_json(self.failed_file, {})
        failures = failure_state.get('failed', []) if isinstance(failure_state, dict) else []
        for slot in ('active', 'previous'):
            path = self.resolve_slot(slot)
            if path is None:
                attempts.append({'slot': slot, 'ok': False, 'reason': 'slot unavailable'})
                continue
            if path.name in failures:
                attempts.append({'slot': slot, 'generation': path.name, 'ok': False,
                                 'reason': 'runtime failure quarantine'})
                continue
            ok, reason, selected = validate_generation(path, checker=self.checker)
            attempts.append({'slot': slot, 'generation': path.name, 'ok': ok, 'reason': reason})
            if ok:
                selected['slot'] = slot
                return selected, attempts
        identity = self.bundle_identity()
        failure = read_json(self.bundle_failed_file, {})
        if identity and failure.get('archive_sha256') == identity:
            attempts.append({'slot': 'bundled', 'ok': False, 'reason': 'bundled runtime failed this boot'})
        elif identity:
            ok, reason, selected = validate_generation(self.bundle, kind='bundled', checker=self.checker)
            attempts.append({'slot': 'bundled', 'ok': ok, 'reason': reason})
            if ok:
                # Namespace immutable identity separately from persistent versions,
                # including for older health-report consumers of generation names.
                selected.update(slot='bundled', archive_sha256=identity,
                                bundled_generation=selected['generation'],
                                generation='iso-' + selected['generation'],
                                working_directory=str(self.base / 'work'))
                return selected, attempts
        else:
            attempts.append({'slot': 'bundled', 'ok': False, 'reason': 'bundled receipt unavailable'})
        return {'kind': 'recovery', 'generation': 'immutable', 'slot': 'recovery',
                'command': self.rescue, 'working_directory': str(self.base / 'work'),
                'full_runtime': False}, attempts

    def apply(self):
        selected, attempts = self.choose()
        self.run.mkdir(parents=True, exist_ok=True)
        write_json(self.run / 'selected.json', selected)
        (self.run / 'runtime.env').write_text(
            'MCP_SOURCE={kind}:{slot}:{generation}\nMCP_COMMAND={command}\nMCP_WORKDIR={working_directory}\n'.format(**selected))
        write_json(self.base / 'state/mcp-selection.json', {'selected': selected, 'attempts': attempts})
        return selected

    def quarantine(self, selected, reason):
        if selected.get('kind') == 'bundled':
            write_json(self.bundle_failed_file, {'archive_sha256': selected.get('archive_sha256'),
                                                'reason': reason})
        elif selected.get('kind') == 'persistent':
            failed = set(read_json(self.failed_file, {}).get('failed', []))
            failed.add(selected['generation'])
            write_json(self.failed_file, {'failed': sorted(failed)})
