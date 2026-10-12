"""Exercise D-Bus activation filename policy only in isolated filesystem trees."""
import ctypes.util
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'ts/build/packages/dbus/build/normalize-dbus-activation'
SESSION = 'usr/share/dbus-1/services'
SYSTEM = 'usr/share/dbus-1/system-services'


class ActivationNamesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ts-dbus-names-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'image'
        self.root.mkdir()

    def record(self, filename='vendor.service', name='org.example.Test', directory=SESSION,
               contents=None):
        path = self.root / directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        text = contents if contents is not None else (
            '[D-BUS Service]\nName=' + name + '\n'
            'Exec=/usr/bin/example --unchanged\n'
            'SystemdService=example.service\nUser=example\n')
        path.write_text(text)
        return path

    def run_helper(self, dry_run=False, env=None):
        args = ['bash', str(HELPER)] + (['--dry-run'] if dry_run else []) + [str(self.root)]
        result = subprocess.run(args, text=True, capture_output=True, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_session_rename_preserves_bytes_metadata_and_inode(self):
        src = self.record()
        src.chmod(0o640)
        os.utime(src, (1234567890, 1234567890))
        content, st = src.read_bytes(), src.stat()
        result = self.run_helper()
        dest = src.with_name('org.example.Test.service')
        self.assertFalse(src.exists())
        self.assertEqual(dest.read_bytes(), content)
        for field in ('st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_mtime_ns'):
            self.assertEqual(getattr(dest.stat(), field), getattr(st, field), field)
        self.assertIn('renamed=1 skipped=0', result.stdout)

    def test_system_bus_is_also_checked(self):
        src = self.record(directory=SYSTEM)
        self.run_helper()
        self.assertTrue(src.with_name('org.example.Test.service').is_file())

    def test_same_name_on_different_buses_is_not_a_conflict(self):
        for directory in (SESSION, SYSTEM):
            self.record(directory=directory)
        result = self.run_helper()
        self.assertIn('renamed=2 skipped=0', result.stdout)

    def test_correct_name_is_unchanged_and_second_run_is_idempotent(self):
        self.record()
        self.run_helper()
        dest = self.root / SESSION / 'org.example.Test.service'
        before = dest.stat()
        result = self.run_helper()
        self.assertIn('renamed=0 skipped=0 already-canonical=1', result.stdout)
        self.assertEqual(dest.stat().st_ino, before.st_ino)

    def test_existing_canonical_provider_is_never_overwritten(self):
        src = self.record()
        dest = self.record('org.example.Test.service')
        before = dest.read_bytes()
        result = self.run_helper()
        self.assertTrue(src.is_file())
        self.assertEqual(dest.read_bytes(), before)
        self.assertIn('multiple providers', result.stderr)

    def test_two_noncanonical_providers_do_not_choose_a_winner(self):
        src = self.record('provider-one.service')
        other = self.record('provider-two.service')
        result = self.run_helper()
        self.assertTrue(src.exists() and other.exists())
        self.assertFalse(src.with_name('org.example.Test.service').exists())
        self.assertIn('renamed=0 skipped=2', result.stdout)

    def test_hidden_activation_provider_participates_in_collision_checks(self):
        src = self.record()
        other = self.record('.hidden.service')
        result = self.run_helper()
        self.assertTrue(src.exists() and other.exists())
        self.assertFalse(src.with_name('org.example.Test.service').exists())
        self.assertIn('multiple providers', result.stderr)

    def test_existing_destination_advertising_another_name_is_preserved(self):
        src = self.record()
        dest = self.record('org.example.Test.service', name='org.example.Other')
        before = dest.read_bytes()
        result = self.run_helper(dry_run=True)
        self.assertTrue(src.exists())
        self.assertEqual(dest.read_bytes(), before)
        self.assertIn('preferred filename occupied', result.stderr)

    def test_initial_occupied_names_are_reserved_for_the_whole_pass(self):
        src = self.record('z-vendor.service')
        dest = self.record('org.example.Test.service', name='org.example.Other')
        before = dest.read_bytes()
        result = self.run_helper()
        self.assertTrue(src.is_file())
        self.assertFalse(dest.exists())
        self.assertEqual(dest.with_name('org.example.Other.service').read_bytes(), before)
        self.assertIn('preferred filename occupied', result.stderr)

    def test_filename_swap_is_not_attempted(self):
        one = self.record('org.example.One.service', name='org.example.Two')
        two = self.record('org.example.Two.service', name='org.example.One')
        before = (one.read_bytes(), two.read_bytes())
        result = self.run_helper()
        self.assertEqual((one.read_bytes(), two.read_bytes()), before)
        self.assertIn('renamed=0 skipped=2', result.stdout)

    def test_local_provider_collision_is_preserved(self):
        src = self.record()
        other = self.record('local.service', directory='usr/local/share/dbus-1/services')
        result = self.run_helper()
        self.assertTrue(src.exists() and other.exists())
        self.assertIn('multiple providers', result.stderr)

    def test_system_admin_and_runtime_providers_are_not_renamed(self):
        for prefix in ('etc', 'run', 'usr/local/share'):
            with self.subTest(prefix=prefix):
                path = self.record('admin.service', directory=prefix + '/dbus-1/system-services')
                self.run_helper()
                self.assertTrue(path.is_file())

    def test_system_admin_override_prevents_vendor_rename(self):
        src = self.record(directory=SYSTEM)
        other = self.record('admin.service', directory='etc/dbus-1/system-services')
        result = self.run_helper()
        self.assertTrue(src.exists() and other.exists())
        self.assertIn('multiple providers', result.stderr)

    def test_dangling_destination_symlink_is_occupied(self):
        src = self.record()
        dest = src.with_name('org.example.Test.service')
        dest.symlink_to('missing-target')
        self.run_helper()
        self.assertTrue(src.is_file())
        self.assertEqual(os.readlink(dest), 'missing-target')

    def test_destination_directory_is_not_a_move_target(self):
        src = self.record()
        dest = src.with_name('org.example.Test.service')
        dest.mkdir()
        self.run_helper()
        self.assertTrue(src.is_file())
        self.assertEqual(list(dest.iterdir()), [])

    def test_symbolic_source_and_external_target_are_untouched(self):
        outside = Path(self.temp.name) / 'outside.service'
        outside.write_text('[D-BUS Service]\nName=org.example.Test\n')
        path = self.root / SESSION / 'alias.service'
        path.parent.mkdir(parents=True)
        path.symlink_to(outside)
        self.run_helper()
        self.assertTrue(path.is_symlink())
        self.assertTrue(outside.exists())
        self.assertFalse(path.with_name('org.example.Test.service').exists())

    def test_directory_symlink_is_not_followed(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        source = outside / 'vendor.service'
        source.write_text('[D-BUS Service]\nName=org.example.Test\n')
        path = self.root / SESSION
        path.parent.mkdir(parents=True)
        path.symlink_to(outside, target_is_directory=True)
        result = self.run_helper()
        self.assertTrue(source.is_file())
        self.assertIn('cannot safely inspect', result.stderr)

    def test_malformed_name_leaves_bus_unchanged(self):
        src = self.record()
        self.record('malformed.service', contents='[D-BUS Service]\nExec=/bin/true\n')
        result = self.run_helper()
        self.assertTrue(src.is_file())
        self.assertIn('incomplete provider inventory', result.stderr)

    def test_duplicate_name_field_is_not_guessed(self):
        self.record(contents='[D-BUS Service]\nName=org.example.A\nName=org.example.B\n')
        result = self.run_helper()
        self.assertIn('ambiguous/missing Name', result.stderr)
        self.assertIn('renamed=0', result.stdout)

    def test_duplicate_service_section_is_not_guessed(self):
        self.record(contents='[D-BUS Service]\nName=org.example.A\n[D-BUS Service]\n')
        self.assertIn('ambiguous/missing Name', self.run_helper().stderr)

    def test_invalid_names_never_become_paths_or_commands(self):
        for name in ('../../escape', 'org.example.$(touch injected)', ':1.5',
                     'org..Test', 'org.5Test', 'org.example.a/b', 'org.' + 'a' * 245):
            with self.subTest(name=name):
                src = self.record(name=name)
                result = self.run_helper()
                self.assertTrue(src.is_file())
                self.assertIn('invalid or overlong', result.stderr)
        self.assertFalse((self.root / 'injected').exists())

    def test_whitespace_comments_crlf_and_other_sections(self):
        src = self.record(contents=(
            '# comment\r\n [D-BUS Service] \r\n Name = org.example.Test \r\n'
            'Exec=/bin/true\r\n[Other]\r\nName=ignored\r\n'))
        before = src.read_bytes()
        self.run_helper()
        self.assertEqual(src.with_name('org.example.Test.service').read_bytes(), before)

    def test_opaque_session_records_do_not_block_system_bus(self):
        self.record(contents='broken\n')
        sys_src = self.record(directory=SYSTEM)
        self.run_helper()
        self.assertTrue(sys_src.with_name('org.example.Test.service').is_file())

    def test_dry_run_does_not_modify_image(self):
        src = self.record()
        result = self.run_helper(dry_run=True)
        self.assertTrue(src.is_file())
        self.assertIn('WOULD RENAME', result.stdout)
        self.assertIn('dry-run=true', result.stdout)

    def test_empty_image_is_valid(self):
        result = self.run_helper()
        self.assertIn('renamed=0 skipped=0', result.stdout)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_root_is_rejected(self):
        result = subprocess.run(['bash', str(HELPER), str(self.root / 'absent')],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_systemd_units_and_policies_are_not_changed(self):
        unit = self.record(directory='etc/systemd/system', contents='[Service]\nExecStart=/bin/true\n')
        policy = self.record(directory='usr/share/dbus-1/system.d', contents='<busconfig/>\n')
        self.run_helper()
        self.assertTrue(unit.is_file() and policy.is_file())

    @unittest.skipUnless(shutil.which('busybox') or shutil.which('busybox.shared'),
                         'BusyBox is not installed')
    def test_busybox_mv_supports_no_clobber_rename(self):
        bindir = Path(self.temp.name) / 'bin'
        bindir.mkdir()
        busybox = shutil.which('busybox.shared') or shutil.which('busybox')
        # Wrapper ensures the shared multicall binary receives the mv applet.
        wrapper = bindir / 'mv'
        wrapper.write_text('#!/bin/sh\nexec "' + busybox + '" mv "$@"\n')
        wrapper.chmod(0o755)
        self.record()
        result = self.run_helper(env=dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH']))
        self.assertIn('renamed=1', result.stdout)

    def test_destination_race_is_not_overwritten(self):
        src = self.record()
        bindir = Path(self.temp.name) / 'bin'
        bindir.mkdir()
        wrapper = bindir / 'mv'
        wrapper.write_text('#!/bin/bash\n'
                           'dest="${!#}"\n'
                           'printf racer > "$dest"\n'
                           'exec "' + shutil.which('mv') + '" "$@"\n')
        wrapper.chmod(0o755)
        result = self.run_helper(env=dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH']))
        self.assertTrue(src.is_file())
        self.assertEqual(src.with_name('org.example.Test.service').read_text(), 'racer')
        self.assertIn('destination appeared', result.stderr)

    def test_six_reported_xfce_names_are_normalized(self):
        mappings = {
            'org.xfce.Thunar.FileManager1': 'org.freedesktop.FileManager1',
            'org.xfce.Tumbler.Cache1': 'org.freedesktop.thumbnails.Cache1',
            'org.xfce.Tumbler.Manager1': 'org.freedesktop.thumbnails.Manager1',
            'org.xfce.Tumbler.Thumbnailer1': 'org.freedesktop.thumbnails.Thumbnailer1',
            'org.xfce.xfce4-notifyd.Notifications': 'org.freedesktop.Notifications',
            'org.xfce.xfce4-notifyd.Notifyd': 'org.xfce.Notifyd',
        }
        for filename, name in mappings.items():
            self.record(filename + '.service', name=name)
        result = self.run_helper()
        self.assertIn('renamed=6 skipped=0', result.stdout)
        self.assertEqual({p.name for p in (self.root / SESSION).iterdir()},
                         {name + '.service' for name in mappings.values()})

    def test_finalizer_calls_helper_without_changing_systemd_enablement(self):
        text = (HELPER.parent / 'finalize').read_text()
        self.assertIn('bash /build/normalize-dbus-activation /', text)
        for scope in ('system', 'user'):
            for unit in ('dbus-broker.service', 'dbus.socket'):
                self.assertIn('install-' + scope + '-units ' + unit, text)

    @unittest.skipUnless(shutil.which('dbus-daemon') and shutil.which('busctl')
                         and ctypes.util.find_library('dbus-1'),
                         'D-Bus daemon, client, and library are required')
    def test_real_private_bus_activates_after_rename(self):
        # No system/session service or live bus is touched. This private bus
        # starts a tiny libdbus fixture and confirms its well-known-name owner.
        work = Path(self.temp.name)
        provider = work / 'provider.py'
        provider.write_text('''import ctypes, ctypes.util, os
lib = ctypes.CDLL(ctypes.util.find_library('dbus-1'))
lib.dbus_connection_open_private.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
lib.dbus_connection_open_private.restype = ctypes.c_void_p
lib.dbus_bus_register.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
lib.dbus_bus_request_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_void_p]
lib.dbus_connection_read_write.argtypes = [ctypes.c_void_p, ctypes.c_int]
lib.dbus_connection_set_exit_on_disconnect.argtypes = [ctypes.c_void_p, ctypes.c_int]
conn = lib.dbus_connection_open_private(os.environ['DBUS_STARTER_ADDRESS'].encode(), None)
assert conn and lib.dbus_bus_register(conn, None)
lib.dbus_connection_set_exit_on_disconnect(conn, 0)
assert lib.dbus_bus_request_name(conn, b'org.example.Test', 4, None) == 1
while lib.dbus_connection_read_write(conn, 1000):
    pass
''')
        src = self.record(contents=('[D-BUS Service]\nName=org.example.Test\n'
            'Exec=' + sys.executable + ' ' + str(provider) + '\n'))
        self.run_helper()
        self.assertFalse(src.exists())
        config = work / 'bus.conf'
        config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=' +
            escape(str(work)) + '</listen><servicedir>' + escape(str(self.root / SESSION)) +
            '</servicedir><policy context="default"><allow send_destination="*"/>'
            '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
        daemon = subprocess.Popen(['dbus-daemon', '--nofork', '--print-address=1',
            '--config-file=' + str(config)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            self.assertTrue(select.select([daemon.stdout], [], [], 5)[0], 'Private bus did not start')
            address = daemon.stdout.readline().strip()
            self.assertTrue(address.startswith('unix:'), address)
            call = ['busctl', '--address=' + address, '--timeout=5', 'call',
                    'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus']
            result = subprocess.run(call + ['StartServiceByName', 'su', 'org.example.Test', '0'],
                                    text=True, capture_output=True, timeout=7)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'u 1')
            owner = subprocess.run(call + ['NameHasOwner', 's', 'org.example.Test'],
                                   text=True, capture_output=True, timeout=7)
            self.assertEqual(owner.returncode, 0, owner.stderr)
            self.assertEqual(owner.stdout.strip(), 'b true')
        finally:
            # Terminate only this private fixture process group, including its
            # auto-started provider, even if an assertion failed.
            import signal
            try:
                os.killpg(daemon.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            daemon.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
