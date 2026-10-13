"""Build-time NetBIOS cleanup should not require a runtime guard or unit override."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "ts/build/packages/mcp-appliance"
FINALIZER = PACKAGE / "build/finalize"
GUARD = PACKAGE / "usr/bin/mcp-firewalld-netbios-guard"
DROPIN = PACKAGE / "etc/systemd/system/firewalld.service.d/20-mcp-netbios.conf"


def cleanup_fragment():
    source = FINALIZER.read_text()
    start = source.split("# BEGIN MCP BUILD-TIME NETBIOS CLEANUP\n", 1)[1]
    return start.split("# END MCP BUILD-TIME NETBIOS CLEANUP", 1)[0]


class NetbiosFinalizeTests(unittest.TestCase):
    def test_no_runtime_guard_or_override(self):
        self.assertFalse(GUARD.exists())
        self.assertFalse(DROPIN.exists())
        fragment = cleanup_fragment()
        self.assertIn("MCP_MODULE_ROOTS", fragment)
        self.assertNotIn("modprobe -n", fragment)
        self.assertIn("nf_conntrack_netbios_ns.ko", fragment)

    def check_case(self, mode):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            module_dir = root / "modules"
            kernel_dir = module_dir / "example-kernel"
            kernel_dir.mkdir(parents=True)
            if mode == "module":
                file = kernel_dir / "kernel/netfilter/nf_conntrack_netbios_ns.ko.xz"
                file.parent.mkdir(parents=True)
                file.write_bytes(b"module")
            elif mode == "builtin":
                (kernel_dir / "modules.builtin").write_text(
                    "kernel/netfilter/nf_conntrack_netbios_ns.ko\n")
            zones = root / "zones"
            zones.mkdir()
            services = root / "services"
            services.mkdir()
            zone_sample = (
                '<zone>\n  <service name="samba-client"/>\n'
                '  <service name="ssh"/>\n  <port port="445" protocol="tcp"/>\n</zone>\n'
            )
            service_sample = (
                '<service>\n  <helper name="netbios-ns"/>\n'
                '  <port port="137" protocol="udp"/>\n</service>\n'
            )
            for name in ("home", "internal", "FedoraWorkstation", "public"):
                (zones / (name + ".xml")).write_text(zone_sample)
            (services / "netbios-ns.xml").write_text(service_sample)
            env = dict(os.environ, MCP_MODULE_ROOTS=str(module_dir),
                       MCP_FIREWALL_ZONE_DIRS=str(zones),
                       MCP_FIREWALL_SERVICE_DIRS=str(services))
            for _ in range(2):  # finalization must be idempotent
                result = subprocess.run(["sh", "-eu", "-c", cleanup_fragment()],
                                        env=env, text=True, capture_output=True,
                                        timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
            for zone in ("home", "internal", "FedoraWorkstation"):
                actual = (zones / (zone + ".xml")).read_text()
                self.assertEqual("samba-client" in actual, mode != "missing")
                self.assertIn('name="ssh"', actual)
                self.assertIn('port="445"', actual)
            self.assertEqual((zones / "public.xml").read_text(), zone_sample)
            service = (services / "netbios-ns.xml").read_text()
            self.assertEqual('name="netbios-ns"' in service, mode != "missing")
            self.assertIn('port="137"', service)

    def test_missing_module_cleanup(self):
        self.check_case("missing")

    def test_module_present_preserves_rules(self):
        self.check_case("module")

    def test_builtin_module_preserves_rules(self):
        self.check_case("builtin")


if __name__ == "__main__":
    unittest.main()
