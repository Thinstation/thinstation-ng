"""Keep usr-merge cleanup separate from service behavior and enablement policy."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / 'ts/build/packages'


def directives(text):
    """Read simple drop-ins while preserving list resets and repeated values."""
    result = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            continue
        key, value = line.split('=', 1)
        result.setdefault((section, key.strip()), []).append(value.strip())
    return result


def dropin(package, unit, scope='system'):
    return PACKAGES / package / 'build/extra/etc/systemd' / scope / (unit + '.d/overrides.conf')


class SystemdOverrideTests(unittest.TestCase):
    def test_path_only_overrides_are_removed(self):
        for package, unit, scope in (
            ('alsa', 'alsa-restore.service', 'system'),
            ('alsa', 'alsa-state.service', 'system'),
            ('cups', 'cups-browsed.service', 'system'),
            ('spice-vdagent', 'spice-vdagentd.service', 'system'),
            ('spice-vdagent', 'spice-vdagent.service', 'user'),
        ):
            with self.subTest(package=package, unit=unit):
                path = dropin(package, unit, scope)
                self.assertFalse(path.exists())
                self.assertFalse(path.is_symlink())

    def test_inactive_logrotate_override_is_removed(self):
        path = dropin('logrotate', 'logrotate.system')
        self.assertFalse(path.exists())
        self.assertFalse(path.is_symlink())

    def test_lightdm_keeps_locale_and_inherits_vendor_command(self):
        self.assertEqual(directives(dropin('lightdm', 'lightdm.service').read_text()), {
            ('Service', 'EnvironmentFile'): ['/etc/locale.conf'],
        })

    def test_regular_sshd_keeps_ordering_and_install_policy(self):
        self.assertEqual(directives(dropin('openssh', 'sshd.service').read_text()), {
            ('Unit', 'After'): ['tsinit.target networkmanager-reload.service'],
            ('Install', 'WantedBy'): ['', 'tsinit.target'],
        })

    def test_socket_sshd_key_policy_is_not_changed_by_path_cleanup(self):
        values = directives(dropin('openssh', 'sshd@.service').read_text())
        self.assertEqual(values[('Service', 'ExecStart')], ['', '-/usr/bin/sshd -i $OPTIONS'])

    def test_networkmanager_wait_behavior_is_not_changed(self):
        values = directives(dropin('networkmanager', 'NetworkManager-wait-online.service').read_text())
        self.assertEqual(values[('Service', 'ExecStart')], ['', '/usr/bin/nm-online -q'])

    def test_qga_has_only_an_empty_optional_argument_default(self):
        values = directives(dropin('qemu-guest-agent', 'qemu-guest-agent.service').read_text())
        self.assertEqual(values[('Service', 'Environment')], ['QEMU_GA_ARGS='])
        for key in ('ExecStart', 'EnvironmentFile', 'UnsetEnvironment'):
            self.assertNotIn(('Service', key), values)

    def test_qga_ordering_restart_and_enablement_are_retained(self):
        values = directives(dropin('qemu-guest-agent', 'qemu-guest-agent.service').read_text())
        self.assertEqual(values[('Unit', 'After')], ['fastboot.service'])
        self.assertEqual(values[('Service', 'Restart')], ['always'])
        self.assertEqual(values[('Service', 'RestartSec')], ['1'])
        self.assertEqual(values[('Install', 'WantedBy')], ['', 'tsinit.target'])
        legacy = PACKAGES / 'qemu-guest-agent/build/extra/etc/systemd/system/tsinit.target.wants/qemu-guest-agent.service'
        self.assertFalse(legacy.exists())
        self.assertFalse(legacy.is_symlink())

    def test_qga_rpm_postinstall_finalizer_is_retained(self):
        text = (PACKAGES / 'qemu-guest-agent/build/finalize').read_text()
        commands = [line.strip() for line in text.splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(commands, ['. /build/scripts/qemu-guest-agent_postinstall.sh 1'])

    def test_lightdm_installer_does_not_rewrite_vendor_units(self):
        with tempfile.TemporaryDirectory(prefix='ts-unit-install-') as temp:
            root = Path(temp)
            payload = root / 'package'
            bindir = root / 'bin'
            bindir.mkdir()
            # A future vendor command may use either executable namespace.
            vendor_text = ('[Service]\nExecStart=/usr/sbin/lightdm\n'
                           'ExecReload=/usr/bin/test -e /usr/bin/lightdm\n')
            vendor = root / 'vendor.service'
            vendor.write_text(vendor_text)
            stub = bindir / 'repackage'
            stub.write_text('''#!/bin/sh
set -eu
mkdir -p "$PAYLOAD/build" "$PAYLOAD/usr/lib64/systemd/system"
for file in usr/bin/lightdm usr/bin/lightdm-gtk-greeter usr/lib64/libxklavier.so.16; do
    mkdir -p "$(dirname "$PAYLOAD/$file")"
    printf payload > "$PAYLOAD/$file"
done
cp "$VENDOR_UNIT" "$PAYLOAD/usr/lib64/systemd/system/lightdm.service"
touch "$PAYLOAD/build/installed"
''')
            stub.chmod(0o755)
            install = root / 'install'
            install.write_text((PACKAGES / 'lightdm/build/install').read_text().replace(
                '/build/packages/lightdm', str(payload)))
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                       PAYLOAD=str(payload), VENDOR_UNIT=str(vendor))
            result = subprocess.run(['sh', str(install)], env=env, text=True,
                                    capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((payload / 'usr/lib64/systemd/system/lightdm.service').read_text(), vendor_text)
            self.assertTrue((payload / 'build/installed').exists())


if __name__ == '__main__':
    unittest.main()
