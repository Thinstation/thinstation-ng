"""MCP firewall cleanup must not alter the shared ThinStation firewalld recipe."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MCP_FINALIZE = ROOT / "ts/build/packages/mcp-appliance/build/finalize"
FIREWALL_FINALIZE = ROOT / "ts/build/packages/firewalld/build/finalize"


class McpFirewallZonesTests(unittest.TestCase):
    def test_cleanup_only_targets_mcp_appliance(self):
        script = MCP_FINALIZE.read_text()
        self.assertIn("# BEGIN MCP FIREWALL NETBIOS CLEANUP", script)
        self.assertIn("# END MCP FIREWALL NETBIOS CLEANUP", script)
        self.assertNotIn("samba-client", FIREWALL_FINALIZE.read_text())
        self.assertNotIn("netbios", FIREWALL_FINALIZE.read_text().lower())

    def test_removes_only_legacy_helper_from_unused_zones(self):
        script = MCP_FINALIZE.read_text()
        commands = script.split("# BEGIN MCP FIREWALL NETBIOS CLEANUP", 1)[1].split(
            "# END MCP FIREWALL NETBIOS CLEANUP", 1)[0]
        with tempfile.TemporaryDirectory(prefix="mcp-firewall-zones-") as temp:
            zones = Path(temp) / "zones"
            zones.mkdir()
            base = """<?xml version="1.0" encoding="utf-8"?>
<zone>
  <service name="ssh"/>
  <service name="samba-client"/>
  <port port="445" protocol="tcp"/>
</zone>
"""
            for zone in ("home", "internal", "FedoraWorkstation", "public"):
                (zones / (zone + ".xml")).write_text(base)
            for name in ("home", "internal", "FedoraWorkstation"):
                target = zones / (name + ".xml")
                self.assertIn("samba-client", target.read_text())
            # Test the exact finalizer shell fragment, not a second copy of
            # its sed expression. Keep the fixture isolated from host zones.
            commands = commands.replace("/etc/firewalld/zones/", str(zones) + "/")
            for _ in range(2):  # Idempotent on repeated finalization
                result = subprocess.run(["sh", "-eu", "-c", commands],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("home", "internal", "FedoraWorkstation"):
                value = (zones / (name + ".xml")).read_text()
                self.assertNotIn("samba-client", value)
                self.assertIn('<service name="ssh"/>', value)
                self.assertIn('<port port="445" protocol="tcp"/>', value)
            self.assertEqual((zones / "public.xml").read_text(), base)

    def test_missing_optional_zones_do_not_fail(self):
        script = MCP_FINALIZE.read_text()
        commands = script.split("# BEGIN MCP FIREWALL NETBIOS CLEANUP", 1)[1].split(
            "# END MCP FIREWALL NETBIOS CLEANUP", 1)[0]
        with tempfile.TemporaryDirectory(prefix="mcp-firewall-empty-") as temp:
            commands = commands.replace("/etc/firewalld/zones/", temp + "/")
            result = subprocess.run(["sh", "-eu", "-c", commands],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
