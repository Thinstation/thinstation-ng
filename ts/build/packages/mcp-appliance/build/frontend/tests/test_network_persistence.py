import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'usr/bin'))
from mcp_network_persistence import attach

class NetworkPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.live = self.root / 'etc/system-connections'
        self.live.mkdir(parents=True, mode=0o700)
        self.store = self.root / 'persistent/network-connections'
        self.store.parent.mkdir(mode=0o700)
    def tearDown(self):
        self.temp.cleanup()
    def profile(self, path, value='[connection]\nid=fixture\n'):
        path.write_text(value)
        path.chmod(0o600)
    def test_migrates_spaced_filename_and_is_idempotent(self):
        self.profile(self.live / 'Wired connection 1.nmconnection')
        attach(self.live, self.store)
        self.assertTrue(self.live.is_symlink())
        self.assertEqual((self.store / 'Wired connection 1.nmconnection').stat().st_mode & 0o777, 0o600)
        attach(self.live, self.store)
    def test_persistent_profiles_win_on_new_boot(self):
        self.store.mkdir(mode=0o700)
        self.profile(self.store / 'saved.nmconnection', 'saved')
        self.profile(self.live / 'default.nmconnection', 'image-default')
        attach(self.live, self.store)
        self.assertEqual((self.live / 'saved.nmconnection').read_text(), 'saved')
        self.assertFalse((self.live / 'default.nmconnection').exists())
    def test_new_profiles_are_persistent(self):
        attach(self.live, self.store)
        self.profile(self.live / 'new.nmconnection', 'new settings')
        self.assertEqual((self.store / 'new.nmconnection').read_text(), 'new settings')
    def test_unexpected_symlink_rejected(self):
        self.live.rmdir()
        self.live.symlink_to(self.root)
        with self.assertRaises(ValueError): attach(self.live, self.store)
    def test_unsafe_profile_rejected(self):
        self.profile(self.live / 'unsafe.nmconnection')
        (self.live / 'unsafe.nmconnection').chmod(0o644)
        with self.assertRaises(ValueError): attach(self.live, self.store)
        self.assertFalse(self.live.is_symlink())
    def test_symlinked_store_rejected(self):
        self.store.symlink_to(self.root)
        with self.assertRaises(ValueError): attach(self.live, self.store)
    def test_existing_backup_not_overwritten(self):
        self.live.with_name('system-connections.boot-defaults').mkdir()
        with self.assertRaises(ValueError): attach(self.live, self.store)

if __name__ == '__main__': unittest.main()
