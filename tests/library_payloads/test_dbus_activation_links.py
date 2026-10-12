"""Canonical RPM activation aliases must not disable unrelated normalization."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'ts/build/packages/dbus/build/normalize-dbus-activation'
SESSION = 'usr/share/dbus-1/services'
SYSTEM = 'usr/share/dbus-1/system-services'


class CanonicalActivationLinksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ts-dbus-link-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'image'
        self.root.mkdir()

    def record(self, directory, filename, name):
        path = self.root / directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[D-BUS Service]\nName=' + name + '\nExec=/bin/false\n')
        return path

    def link(self, name, target):
        path = self.root / SESSION / (name + '.service')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        return path

    def candidate(self):
        return self.record(SESSION, 'vendor.service', 'org.example.Candidate')

    def run_helper(self):
        result = subprocess.run(['bash', str(HELPER), str(self.root)],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_systemd_cross_bus_alias_keeps_link_and_allows_rename(self):
        target = self.record(SYSTEM, 'org.freedesktop.systemd1.service', 'org.freedesktop.systemd1')
        link = self.link('org.freedesktop.systemd1', '../system-services/' + target.name)
        source = self.candidate()
        before = target.read_bytes()
        result = self.run_helper()
        self.assertIn('renamed=1 skipped=0', result.stdout)
        self.assertTrue(source.with_name('org.example.Candidate.service').is_file())
        self.assertEqual(os.readlink(link), '../system-services/' + target.name)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(result.stderr, '')

    def test_absolute_alias_is_resolved_in_image_not_host(self):
        target = self.record(SYSTEM, 'org.example.Alias.service', 'org.example.Alias')
        link = self.link('org.example.Alias', '/' + SYSTEM + '/' + target.name)
        self.candidate()
        result = self.run_helper()
        self.assertIn('renamed=1 skipped=0', result.stdout)
        self.assertTrue(link.is_symlink())
        self.assertEqual(result.stderr, '')

    def test_multihop_leaf_links_are_preserved(self):
        target = self.record(SYSTEM, 'org.example.Alias.service', 'org.example.Alias')
        middle = self.root / 'intermediate'
        middle.symlink_to('/' + SYSTEM + '/' + target.name)
        link = self.link('org.example.Alias', '/intermediate')
        self.candidate()
        self.assertIn('renamed=1 skipped=0', self.run_helper().stdout)
        self.assertEqual(os.readlink(link), '/intermediate')
        self.assertTrue(middle.is_symlink())

    def test_canonical_alias_counts_as_competing_provider(self):
        target = self.record(SYSTEM, 'org.example.Shared.service', 'org.example.Shared')
        self.link('org.example.Shared', '../system-services/' + target.name)
        source = self.record(SESSION, 'vendor.service', 'org.example.Shared')
        result = self.run_helper()
        self.assertTrue(source.exists())
        self.assertIn('multiple providers', result.stderr)
        self.assertIn('renamed=0 skipped=1', result.stdout)

    def test_symlink_cycle_blocks_normalization(self):
        one = self.link('org.example.Alias', '/cycle')
        (self.root / 'cycle').symlink_to('/' + SESSION + '/' + one.name)
        source = self.candidate()
        result = self.run_helper()
        self.assertTrue(source.exists())
        self.assertIn('unresolved activation link', result.stderr)

    def test_relative_link_cannot_escape_image_root(self):
        self.link('org.example.Alias', '../../../../../outside.service')
        outside = Path(self.temp.name) / 'outside.service'
        outside.write_text('[D-BUS Service]\nName=org.example.Alias\n')
        source = self.candidate()
        self.assertIn('unresolved activation link', self.run_helper().stderr)
        self.assertTrue(source.exists() and outside.exists())

    def test_directory_link_in_target_is_not_traversed(self):
        target = self.record(SYSTEM, 'org.example.Alias.service', 'org.example.Alias')
        (self.root / 'route').symlink_to(SYSTEM, target_is_directory=True)
        self.link('org.example.Alias', '/route/' + target.name)
        source = self.candidate()
        self.assertIn('unresolved activation link', self.run_helper().stderr)
        self.assertTrue(source.exists())

    def test_alias_must_match_its_advertised_name(self):
        target = self.record(SYSTEM, 'org.example.Other.service', 'org.example.Other')
        self.link('org.example.Alias', '../system-services/' + target.name)
        source = self.candidate()
        self.assertIn('noncanonical activation link', self.run_helper().stderr)
        self.assertTrue(source.exists())

    def test_alias_target_must_already_be_canonical(self):
        target = self.record('data', 'legacy.service', 'org.example.Alias')
        self.link('org.example.Alias', '/data/' + target.name)
        source = self.candidate()
        self.assertIn('noncanonical activation link', self.run_helper().stderr)
        self.assertTrue(source.exists() and target.exists())


if __name__ == '__main__':
    unittest.main()
