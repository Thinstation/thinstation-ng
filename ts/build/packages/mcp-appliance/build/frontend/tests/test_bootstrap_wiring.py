from pathlib import Path
import unittest

PACKAGE = Path(__file__).resolve().parents[3]
UNITS = PACKAGE / 'usr/lib64/systemd/system'


def directive(text, key):
    return [value.strip() for line in text.splitlines()
            for name, sep, value in [line.partition('=')]
            if sep and name.strip() == key]


class ApplianceBootTests(unittest.TestCase):
    def test_tunnel_is_part_of_existing_appliance_boot_dependency(self):
        identity = (UNITS / 'mcp-sshd-hostkey.service').read_text()
        wants = ' '.join(directive(identity, 'Wants')).split()
        for service in ('mcp-appliance-web.service', 'mcp-runtime.service',
                        'mcp-openai-tunnel.service'):
            self.assertIn(service, wants)

    def test_tunnel_remains_opt_in_and_ordered_after_runtime(self):
        tunnel = (UNITS / 'mcp-openai-tunnel.service').read_text()
        self.assertEqual(directive(tunnel, 'ConditionPathExists'),
                         ['/var/prstnt/mcp-appliance/connections/openai/enabled'])
        self.assertIn('mcp-runtime.service', ' '.join(directive(tunnel, 'After')).split())
        self.assertIn('mcp-appliance-init.service', ' '.join(directive(tunnel, 'After')).split())

    def test_failed_tunnel_does_not_require_stopping_local_mcp(self):
        identity = (UNITS / 'mcp-sshd-hostkey.service').read_text()
        self.assertNotIn('mcp-openai-tunnel.service', ' '.join(directive(identity, 'Requires')).split())
        tunnel = (UNITS / 'mcp-openai-tunnel.service').read_text()
        self.assertEqual(directive(tunnel, 'PartOf'), [])


if __name__ == '__main__':
    unittest.main()
