#!/usr/bin/python3
"""Unpack one checksum-pinned MCP release into the image package, not persistence."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

PYTHONS = {'/usr/bin/python3', '/usr/bin/python3.14'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def unpack(archive, target, generation):
    """Extract data first, links last; never write through an archive symlink."""
    links, hardlinks, seen = [], [], set()
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:*') as source:
        members = source.getmembers()
        if len(members) > 100000 or sum(m.size for m in members) > 2 * 1024 ** 3:
            raise ValueError('fallback archive exceeds size limits')
        for item in members:
            path = PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != generation:
                raise ValueError('unsafe or unexpected archive path: ' + item.name)
            relative = Path(*path.parts[1:])
            if not path.parts[1:]:
                if not item.isdir():
                    raise ValueError('archive root is not a directory')
                continue
            if '.git' in relative.parts or any(p == '.env' or p.startswith('.env.') for p in relative.parts):
                raise ValueError('development credentials must not enter the ISO')
            if str(relative) in seen:
                raise ValueError('duplicate archive member: ' + item.name)
            seen.add(str(relative))
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            if item.isdir():
                dest.mkdir(exist_ok=True)
            elif item.isfile():
                with source.extractfile(item) as stream, dest.open('xb') as output:
                    shutil.copyfileobj(stream, output)
                dest.chmod((item.mode & 0o755) | 0o400)
            elif item.issym():
                links.append((relative, item.linkname))
            elif item.islnk():
                hardlinks.append((relative, item.linkname))
            else:
                raise ValueError('special file in fallback archive: ' + item.name)
        for relative, link in hardlinks:
            path = PurePosixPath(link)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != generation:
                raise ValueError('unsafe hardlink')
            source_path = target.joinpath(*path.parts[1:])
            if not source_path.is_file() or source_path.is_symlink():
                raise ValueError('hardlink target is not an extracted regular file')
            os.link(source_path, target / relative)
        for relative, link in links:
            dest = target / relative
            interpreter = relative.parent == Path('.venv/bin') and relative.name in ('python', 'python3', 'python3.14')
            if Path(link).is_absolute():
                if not interpreter or link not in PYTHONS:
                    raise ValueError('unsafe absolute symlink: ' + str(relative))
            else:
                logical = Path(os.path.normpath(str(relative.parent / link)))
                if logical.is_absolute() or '..' in logical.parts:
                    raise ValueError('unsafe relative symlink: ' + str(relative))
            dest.symlink_to(link)
        # Check completed chains, allowing only the deliberate interpreter aliases.
        for relative, _ in links:
            resolved = (target / relative).resolve()
            try:
                resolved.relative_to(target.resolve())
            except ValueError:
                interpreter = relative.parent == Path('.venv/bin') and relative.name in ('python', 'python3', 'python3.14')
                if not interpreter or not any(resolved == Path(p).resolve() for p in PYTHONS):
                    raise ValueError('archive link chain escapes payload: ' + str(relative))


def install(package):
    package = Path(package).resolve()
    descriptor = json.loads((package / 'build/bundled-mcp.json').read_text())
    generation = descriptor['generation']
    expected = descriptor['sha256']
    if not isinstance(generation, str) or not generation or generation in ('.', '..') or any(not (c.isascii() and (c.isalnum() or c in '._-')) for c in generation):
        raise ValueError('invalid pinned generation')
    if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('invalid pinned SHA256')
    if not descriptor['url'].startswith('https://'):
        raise ValueError('bundled artifact requires HTTPS')
    dest = package / 'usr/lib64/mcp-fallback'
    with tempfile.TemporaryDirectory(prefix='mcp-bundle-', dir=package / 'build') as work:
        work = Path(work)
        archive = work / 'generation.tar.gz'
        subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location',
                        '--proto', '=https', '--proto-redir', '=https',
                        '--connect-timeout', '15', '--max-time', '300',
                        '--output', str(archive), descriptor['url']], check=True)
        if digest(archive) != expected:
            raise ValueError('bundled artifact SHA256 mismatch')
        tree = work / 'payload'
        unpack(archive, tree, generation)
        manifest = json.loads((tree / 'manifest.json').read_text())
        if manifest.get('name') != generation or manifest.get('source_sha') != descriptor['source_sha']:
            raise ValueError('bundled source identity does not match pin')
        for rel, sha in manifest.get('sha256', {}).items():
            path = (tree / rel).resolve()
            path.relative_to(tree.resolve())
            if digest(path) != sha:
                raise ValueError('bundled manifest hash mismatch: ' + rel)
        if not (tree / 'app/server.py').is_file() or not (tree / '.venv/bin/python').is_file():
            raise ValueError('full MCP runtime is absent from archive')
        (tree / 'qualification.json').unlink(missing_ok=True)
        receipt = dict(generation=generation, version=descriptor['version'],
                       source_sha=descriptor['source_sha'], archive_sha256=expected)
        (tree / 'bundled.json').write_text(json.dumps(receipt, indent=2) + '\n')
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(tree, dest)
    print('Staged full MCP baseline: ' + generation + ' (' + expected + ')', flush=True)


if __name__ == '__main__':
    install(sys.argv[1])
