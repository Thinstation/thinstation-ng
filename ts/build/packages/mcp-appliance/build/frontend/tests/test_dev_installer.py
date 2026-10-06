import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

BUILD = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('dev_installer', BUILD / 'install-dev-operator.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
SHA = 'a' * 40


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = self.root / 'release.tar.gz'
    def tearDown(self):
        self.tmp.cleanup()
    def bundle(self, changes=None, omit=None, extra=False, link=False):
        files = {'index.html': b'<html>test</html>'}
        for name in installer.BACKEND_FILES:
            files['_operator/' + name] = installer.UNIT_TEMPLATE.encode() if name.endswith('.service') else b'# Python fixture\n'
        files.update(changes or {})
        checksums = {name: hashlib.sha256(data).hexdigest() for name, data in files.items() if name != omit}
        files['operator-release.json'] = json.dumps({'version': 1, 'source_sha': SHA, 'pipeline': '42', 'files': checksums}).encode()
        with tarfile.open(self.archive, 'w:gz') as tf:
            for name, data in files.items():
                info = tarfile.TarInfo(name); info.size = len(data); tf.addfile(info, io.BytesIO(data))
            if extra:
                info = tarfile.TarInfo('../escape'); info.size = 1; tf.addfile(info, io.BytesIO(b'x'))
            if link:
                info = tarfile.TarInfo('symlink'); info.type = tarfile.SYMTYPE; info.linkname = '/etc/passwd'; tf.addfile(info)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()
    def verify(self, digest, sha=SHA):
        return installer.verify_bundle(self.archive, self.root / 'web', sha, '42', digest)
    def test_valid_paired_bundle(self):
        self.assertEqual(self.verify(self.bundle())['source_sha'], SHA)
    def test_bad_archive_digest(self):
        self.bundle()
        with self.assertRaisesRegex(ValueError, 'checksum'): self.verify('b' * 64)
    def test_wrong_source_commit(self):
        with self.assertRaisesRegex(ValueError, 'requested build'): self.verify(self.bundle(), 'b' * 40)
    def test_unlisted_file_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly'): self.verify(self.bundle(omit='index.html'))
    def test_path_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsafe'): self.verify(self.bundle(extra=True))
        self.assertFalse((self.root.parent / 'escape').exists())
    def test_symlink_rejected(self):
        with self.assertRaisesRegex(ValueError, 'link'): self.verify(self.bundle(link=True))
    def test_service_template_tampering_rejected(self):
        with self.assertRaisesRegex(ValueError, 'reviewed template'): self.verify(self.bundle({'_operator/mcp-openai-tunnel.service': installer.UNIT_TEMPLATE.replace('NoNewPrivileges=yes', 'NoNewPrivileges=no').encode()}))
    def test_unexpected_backend_rejected(self):
        with self.assertRaisesRegex(ValueError, 'backend'): self.verify(self.bundle({'_operator/extra.py': b'# not allowed'}))
    def test_packaged_service_matches_reviewed_template(self):
        self.assertEqual((BUILD.parent / 'usr/lib64/systemd/system/mcp-openai-tunnel.service').read_text(), installer.UNIT_TEMPLATE)
    def test_active_tunnel_blocks_installation(self):
        with patch.object(installer, 'BASE', self.root), patch.object(installer.subprocess, 'run') as run:
            run.return_value.stdout = 'active\n'
            with self.assertRaisesRegex(ValueError, 'inactive'): installer.require_idle_tunnel()
    def test_enabled_tunnel_blocks_installation(self):
        enabled = self.root / 'connections/openai/enabled'; enabled.parent.mkdir(parents=True); enabled.touch()
        with patch.object(installer, 'BASE', self.root), patch.object(installer.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Disconnect'): installer.require_idle_tunnel()
            run.assert_not_called()


if __name__ == '__main__': unittest.main()
