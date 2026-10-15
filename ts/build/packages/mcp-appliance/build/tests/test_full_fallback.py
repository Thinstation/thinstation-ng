"""Small deterministic selection tests; no live services or credentials."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE / 'usr/bin'))
from mcp_runtime import Selector, write_json


class SelectionTests(unittest.TestCase):
    def setUp(self):
        # CI intentionally mounts /tmp noexec; use its executable workspace.
        self.temp = tempfile.TemporaryDirectory(prefix='.fallback-test-', dir=os.environ.get('CI_PROJECT_DIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'persistent'
        self.run = self.root / 'run'
        self.bundle = self.root / 'bundle'
        self.selector = Selector(self.base, self.run, self.bundle)
        self.gen(self.bundle, 'thinstation-mcp-build-309')
        write_json(self.bundle / 'bundled.json', {'archive_sha256': 'a' * 64})

    def gen(self, path, name, test=''):
        path.mkdir(parents=True, exist_ok=True)
        executable = path / 'run.sh'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        write_json(path / 'manifest.json', {'name': name, 'command': './run.sh', 'self_test': test})
        return path

    def slot(self, name, generation, test=''):
        path = self.gen(self.base / 'mcp/generations' / generation, generation, test)
        (self.base / 'mcp' / name).symlink_to(Path('generations') / generation)
        return path

    def test_fresh_install_uses_bundle_without_creating_active(self):
        selected, attempts = self.selector.choose()
        self.assertEqual(selected['kind'], 'bundled', attempts)
        self.assertFalse((self.base / 'mcp/active').exists())

    def test_active_wins(self):
        self.slot('active', 'upgrade-1')
        selected, attempts = self.selector.choose()
        self.assertEqual((selected['kind'], selected['slot']), ('persistent', 'active'), attempts)

    def test_previous_wins_after_failed_active(self):
        self.slot('active', 'upgrade-1', 'exit 7')
        self.slot('previous', 'upgrade-0')
        selected, attempts = self.selector.choose()
        self.assertEqual(selected['slot'], 'previous', attempts)
        self.assertIn('preflight', attempts[0]['reason'])

    def test_persistent_quarantine_does_not_block_same_version_bundle(self):
        name = 'thinstation-mcp-build-309'
        self.slot('active', name)
        write_json(self.selector.failed_file, {'failed': [name]})
        selected, attempts = self.selector.choose()
        self.assertEqual(selected['kind'], 'bundled', attempts)
        self.assertEqual(selected['bundled_generation'], name)
        self.assertNotEqual(selected['generation'], name)

    def test_bundle_failure_falls_to_rescue(self):
        selected, _ = self.selector.choose()
        self.selector.quarantine(selected, 'test crash')
        selected, _ = self.selector.choose()
        self.assertEqual(selected['kind'], 'recovery')
        self.assertFalse(self.selector.failed_file.exists())

    def test_new_iso_receipt_retries_bundle(self):
        selected, _ = self.selector.choose()
        self.selector.quarantine(selected, 'test crash')
        write_json(self.bundle / 'bundled.json', {'archive_sha256': 'b' * 64})
        selected, attempts = self.selector.choose()
        self.assertEqual(selected['kind'], 'bundled', attempts)

    def test_invalid_manifest_keeps_recovery_available(self):
        (self.bundle / 'manifest.json').write_text('{bad')
        selected, _ = self.selector.choose()
        self.assertEqual(selected['kind'], 'recovery')

    def test_slot_escape_is_rejected(self):
        (self.base / 'mcp').mkdir(parents=True)
        (self.base / 'mcp/generations').mkdir()
        (self.base / 'mcp/active').symlink_to(self.bundle)
        self.assertIsNone(self.selector.resolve_slot('active'))

    def test_apply_records_actual_selection(self):
        selected = self.selector.apply()
        self.assertEqual(json.loads((self.run / 'selected.json').read_text()), selected)
        self.assertIn('MCP_SOURCE=bundled:bundled:', (self.run / 'runtime.env').read_text())
        self.assertEqual(json.loads((self.base / 'state/mcp-selection.json').read_text())['selected'], selected)


if __name__ == '__main__':
    unittest.main()
