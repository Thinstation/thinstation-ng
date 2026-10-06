import unittest
from pathlib import Path

class AuthorizationSurfaceTests(unittest.TestCase):
    def test_certificates_page_uses_dedicated_operator_routes(self):
        root=Path(__file__).resolve().parents[1]
        ui=(root/'src/Certificates.svelte').read_text()
        self.assertIn("endpoint+'/authorization/'+kind",ui)
        self.assertIn("authorize('once')",ui)
        self.assertIn("authorize('automatic')",ui)
        self.assertIn("authorize('revoke')",ui)
        self.assertNotIn("'/api/vault/grant'",ui)
    def test_operator_routes_do_not_take_scope_or_credential_from_client(self):
        root=Path(__file__).resolve().parents[3]
        web=(root/'usr/bin/mcp-operator-web').read_text()
        self.assertIn("certificates.authorize_once(self.user['username'])",web)
        self.assertIn("certificates.authorize_automatic(str(body.get('revision','')),self.user['username'])",web)

if __name__=='__main__':unittest.main()
