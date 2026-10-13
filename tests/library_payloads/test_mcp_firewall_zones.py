"""Check conditional NetBIOS cleanup hooked into appliance firewalld startup."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "ts/build/packages/mcp-appliance"
GUARD = PACKAGE / "usr/bin/mcp-firewalld-netbios-guard"
DROPIN = PACKAGE / "etc/systemd/system/firewalld.service.d/20-mcp-netbios.conf"

class NetbiosGuardTests(unittest.TestCase):
    def test_files_are_in_direct_payload_not_repackage_extra(self):
        self.assertTrue(GUARD.is_file())
        self.assertTrue(DROPIN.is_file())
        self.assertFalse((PACKAGE / "build/extra/usr/bin/mcp-firewalld-netbios-guard").exists())
        self.assertFalse((PACKAGE / "build/extra/etc/systemd/system/firewalld.service.d/20-mcp-netbios.conf").exists())

    def test_dropin_runs_before_firewalld(self):
        data = DROPIN.read_text()
        self.assertIn("ExecStartPre=/usr/bin/mcp-firewalld-netbios-guard", data)
        self.assertIn("After=persistent-files.service persistent-dirs.service", data)

    def test_conditional_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            zones = root / "zones"
            zones.mkdir()
            services = root / "services"
            services.mkdir()
            service = services / "netbios-ns.xml"
            service_sample = '<service>\\n  <helper name="netbios-ns"/>\\n  <port protocol="udp" port="137"/>\\n</service>\\n'
            service_sample = service_sample.replace('\\n', '\n')
            service.write_text(service_sample)
            tools = root / "bin"
            tools.mkdir()
            mod = tools / "modprobe"
            mod.write_text("#!/bin/sh\nexit ${MODULE_PRESENT:-1}\n")
            mod.chmod(0o755)
            sample = '<zone>\n  <service name="samba-client"/>\n  <service name="ssh"/>\n</zone>\n'
            for name in ("home", "internal", "FedoraWorkstation", "public"):
                (zones / (name + ".xml")).write_text(sample)
            env = dict(os.environ, FIREWALL_ZONE_DIR=str(zones), FIREWALL_SERVICE_DIR=str(services),
                       PATH=str(tools) + os.pathsep + os.environ["PATH"])
            # Module present: don't touch any zone.
            env["MODULE_PRESENT"] = "0"
            result = subprocess.run(["sh", str(GUARD)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((zones / "home.xml").read_text(), sample)
            self.assertEqual(service.read_text(), service_sample)
            # Module missing: change only target zones, repeat safely.
            env["MODULE_PRESENT"] = "1"
            for _ in range(2):
                result = subprocess.run(["sh", str(GUARD)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("home", "internal", "FedoraWorkstation"):
                self.assertNotIn("samba-client", (zones / (name + ".xml")).read_text())
                self.assertIn('name="ssh"', (zones / (name + ".xml")).read_text())
            self.assertEqual((zones / "public.xml").read_text(), sample)
            self.assertNotIn('<helper name="netbios-ns"/>', service.read_text())
            self.assertIn('port="137"', service.read_text())

if __name__ == "__main__":
    unittest.main()
