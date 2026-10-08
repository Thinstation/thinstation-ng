"""Non-destructive tests of disposable environment manifest validation."""
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[3] / 'usr' / 'bin' / 'mcp_environment_rebuild.py'
spec = importlib.util.spec_from_file_location('mcp_environment_rebuild', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ManifestSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'chroots'
        self.manifests = self.base / 'manifests'
        self.root.mkdir()
        self.manifests.mkdir()
        self.root_patch = patch.object(module, 'ROOT', self.root)
        self.manifest_patch = patch.object(module, 'MANIFEST', self.manifests)
        self.root_patch.start()
        self.manifest_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.manifest_patch.stop)

    def write(self, data):
        (self.manifests / 'test-f44.json').write_text(json.dumps(data))

    def test_active_mount_blocks_replacement(self):
        active=self.root/'test-f44'
        active.mkdir()
        mounts=f'23 22 0:15 / {active} rw - tmpfs tmpfs rw'
        with patch.object(module.Path, 'read_text', autospec=True) as read:
            def fake(path, *args, **kwargs):
                if str(path)=='/proc/self/mountinfo':return mounts
                return ''
            read.side_effect=fake
            with self.assertRaisesRegex(RuntimeError,'active mounts'):
                module.assert_inactive(active)

    def test_idle_root_allowed(self):
        idle=self.root/'test-f44'
        idle.mkdir()
        module.assert_inactive(idle)

    def test_invalid_name_rejected(self):
        with self.assertRaises(ValueError):
            module.rebuild('../outside', '0123456789abcdef0123456789abcdef', io.StringIO(), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_manifest_required(self):
        with self.assertRaises(FileNotFoundError):
            module.rebuild('test-f44', '0123456789abcdef0123456789abcdef', io.StringIO(), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_reject_empty_package_list_without_changing_root(self):
        self.write({'release':'44', 'packages':[]})
        with self.assertRaises(ValueError):
            module.rebuild('test-f44', '0123456789abcdef0123456789abcdef', io.StringIO(), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_reject_package_option_injection(self):
        self.write({'release':'44', 'packages':['--allowerasing']})
        with self.assertRaises(ValueError):
            module.rebuild('test-f44', '0123456789abcdef0123456789abcdef', io.StringIO(), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_failed_package_install_preserves_old_environment(self):
        self.write({'release':'44', 'packages':['bash']})
        active=self.root/'test-f44'
        active.mkdir()
        marker=active/'unchanged'
        marker.write_text('preserved')
        import subprocess
        with patch.object(module.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['dnf'])):
            with self.assertRaises(subprocess.CalledProcessError):
                module.rebuild('test-f44','0123456789abcdef0123456789abcdef',io.StringIO(),[])
        self.assertEqual(marker.read_text(),'preserved')
        self.assertFalse((self.root/'.stage-0123456789abcdef0123456789abcdef').exists())

if __name__ == '__main__':
    unittest.main()
