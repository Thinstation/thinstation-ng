"""Verify normal CI builds avoid deep tests, while debug mode remains available."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class OptionalRegressionModeTests(unittest.TestCase):
    def test_regression_jobs_are_opt_in(self):
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        self.assertIn('RUN_REGRESSION_TESTS:', ci)
        self.assertIn('value: "0"', ci.split('RUN_REGRESSION_TESTS:', 1)[1].split('\n', 3)[1])
        for job in ("test-library-payloads:", "test-mcp-environments:"):
            block = ci.split('\n' + job + '\n', 1)[1].split('\n  script:', 1)[0]
            self.assertIn("if: '$RUN_REGRESSION_TESTS == \"1\"'", block)
        build = ci.split('\nbuild-thinstation-ng:\n', 1)[1].split('\n  script:', 1)[0]
        self.assertIn("optional: true", build)

    def test_frontend_build_is_fast_by_default(self):
        package = json.loads((ROOT / "ts/build/packages/mcp-appliance/build/frontend/package.json").read_text())
        scripts = package["scripts"]
        self.assertNotIn("npm test", scripts["build"])
        self.assertIn("vite build", scripts["build"])
        self.assertIn("npm test", scripts["build:debug"])
        self.assertIn("npm run build", scripts["build:debug"])


if __name__ == "__main__":
    unittest.main()
