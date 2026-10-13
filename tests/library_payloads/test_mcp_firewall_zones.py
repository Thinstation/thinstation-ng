"""Check conditional NetBIOS cleanup hooked into appliance firewalld startup."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "ts/build/packages/mcp-appliance"
GUARD = PACKAGE / "build/extra/usr/bin/mcp-firewalld-netbios-guard"
DROPIN = PACKAGE / "build/extra/etc/systemd/system/firewalld.service.d/20-mcp-netbios.conf"

class NetbiosGuardTests(unittest.TestCase):
    def test_dropin_runs_before_firewalld(self):
        data = DROPIN.read_text()
        self.assertIn("ExecStartPre=/usr/bin/mcp-firewalld-netbios-guard", data)
        self.assertIn("After=persistent-files.service persistent-dirs.service", data)

    def test_conditional_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            zones = root / "zones"
            zones.mkdir()
            tools = root / "bin"
            tools.mkdir()
            mod = tools / "modprobe"
            mod.write_text("#!/bin/sh\nexit ${MODULE_PRESENT:-1}\n")
            mod.chmod(0o755)
            sample = '<zone>\n  <service name="samba-client"/>\n  <service name="ssh"/>\n</zone>\n'
            for name in ("home", "internal", "FedoraWorkstation", "public"):
                (zones / (name + ".xml")).write_text(sample)
            env = dict(os.environ, FIREWALL_ZONE_DIR=str(zones),
                       PATH=str(tools) + os.pathsep + os.environ["PATH"])
            # Module present: don't touch any zone.
            env["MODULE_PRESENT"] = "0"
            result = subprocess.run(["sh", str(GUARD)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((zones / "home.xml").read_text(), sample)
            # Module missing: change only target zones, repeat safely.
            env["MODULE_PRESENT"] = "1"
            for _ in range(2):
                result = subprocess.run(["sh", str(GUARD)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("home", "internal", "FedoraWorkstation"):
                self.assertNotIn("samba-client", (zones / (name + ".xml")).read_text())
                self.assertIn('name="ssh"', (zones / (name + ".xml")).read_text())
            self.assertEqual((zones / "public.xml").read_text(), sample)

if __name__ == "__main__":
    unittest.main()
