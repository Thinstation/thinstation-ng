"""Exercise package guards and console migration in isolated temporary trees."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BUILD = Path(__file__).resolve().parents[1]


class ConsoleMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_migration(self):
        return subprocess.run(
            ['sh', str(BUILD / 'lightdm-restore-console'), str(self.root)],
            text=True, capture_output=True, check=True,
        )

    def test_removes_only_legacy_empty_template_reset(self):
        bad = self.write('usr/lib64/systemd/system/getty@.service.d/disable-tty1.conf',
                         '[Service]\n# Old tty1 workaround\nExecStart=\n')
        other = self.write('usr/lib64/systemd/system/getty@.service.d/operator.conf',
                           '[Service]\nEnvironment=KEEP=1\n')
        self.run_migration()
        self.assertFalse(bad.exists())
        self.assertTrue(other.exists())
        self.run_migration()  # Idempotent migration.

    def test_preserves_valid_replacement_command(self):
        good = self.write('etc/systemd/system/getty@.service.d/disable-tty1.conf',
                          '[Service]\nExecStart=\nExecStart=/usr/bin/agetty %I\n')
        before = good.read_text()
        self.run_migration()
        self.assertEqual(good.read_text(), before)

    def test_preserves_instance_specific_override(self):
        instance = self.write('etc/systemd/system/getty@tty1.service.d/disable-tty1.conf',
                              '[Service]\nExecStart=\n')
        self.run_migration()
        self.assertTrue(instance.exists())

    def test_handles_usrmerge_aliases_and_whitespace(self):
        target = self.write('usr/lib64/systemd/system/getty@.service.d/disable-tty1.conf',
                            ' ; old workaround\n [Service] \n ExecStart =  \n')
        (self.root / 'usr/lib').symlink_to('lib64')
        (self.root / 'lib').symlink_to('usr/lib64')
        self.run_migration()
        self.assertFalse(target.exists())
        self.assertTrue((self.root / 'usr/lib').is_symlink())

    def test_empty_image_is_unchanged(self):
        self.run_migration()
        self.assertEqual(list(self.root.iterdir()), [])


class PackageGuardTests(unittest.TestCase):
    def run_install(self, omit='', repackage_exit=0):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / 'package'
            bindir = root / 'bin'
            bindir.mkdir()
            stub = bindir / 'repackage'
            stub.write_text('''#!/bin/sh
case " $PORTS " in *" libxklavier "*) ;; *) exit 91 ;; esac
[ "$STUB_EXIT" = 0 ] || exit "$STUB_EXIT"
mkdir -p "$PAYLOAD/build" "$PAYLOAD/usr/lib64/systemd/system"
printf marker > "$PAYLOAD/build/installed"
for file in usr/bin/lightdm usr/bin/lightdm-gtk-greeter usr/lib64/libxklavier.so.16; do
    [ "$file" = "$OMIT" ] && continue
    mkdir -p "$(dirname "$PAYLOAD/$file")"
    printf payload > "$PAYLOAD/$file"
done
printf '[Service]\\nExecStart=/usr/bin/lightdm\\n' > "$PAYLOAD/usr/lib64/systemd/system/lightdm.service"
''')
            stub.chmod(0o755)
            # Substitute only the fixed package root; run the actual installer
            # logic with a mock repackage command, never against /build.
            install = root / 'install'
            install.write_text((BUILD / 'install').read_text().replace(
                '/build/packages/lightdm', str(package)))
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                       PAYLOAD=str(package), OMIT=omit, STUB_EXIT=str(repackage_exit))
            result = subprocess.run(['sh', str(install)], env=env,
                                    text=True, capture_output=True)
            return result, (package / 'build/installed').exists()

    def test_complete_payload_succeeds(self):
        result, marker = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker)

    def test_missing_library_fails_and_invalidates_cache(self):
        result, marker = self.run_install(omit='usr/lib64/libxklavier.so.16')
        self.assertEqual(result.returncode, 1)
        self.assertIn('missing usr/lib64/libxklavier.so.16', result.stderr)
        self.assertFalse(marker)

    def test_missing_greeter_fails(self):
        result, marker = self.run_install(omit='usr/bin/lightdm-gtk-greeter')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(marker)

    def test_repackage_failure_is_propagated(self):
        result, _ = self.run_install(repackage_exit=37)
        self.assertEqual(result.returncode, 37)


if __name__ == '__main__':
    unittest.main()
