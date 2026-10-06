# Certificate settings form

The certificate authority, account contact, and requested DNS names are common to every validation method. Custom CA addresses omit the scheme in the form; the backend adds HTTPS. Choosing HTTP-01 does not downgrade CA communication to HTTP. DNS names themselves never need a scheme. Full HTTP(S) origins pasted as certificate names are normalized only when they contain no credentials, port, non-root path, query or fragment.

## Active method fields

- AD DNS-01: select a Windows inventory host with a canonical FQDN, then choose an eligible Active Directory vault credential. Zone and realm can be adjusted; TTL and propagation timeout remain DNS-only settings. Host/group restrictions and acme scope remain enforced. A host listing is not proof it is a domain controller or DNS authority; use the separate connection test.
- Custom DNS-01: installed hook and its vault credential, without AD or listener fields.
- Appliance HTTP-01: temporary responder, allowed validation source networks or explicit public access, and port-80 authorization. No DNS credentials or AD settings are submitted.
- External HTTP-01: webroot instructions and route confirmation. No appliance firewall settings are submitted.
- TLS-ALPN-01: shown as unavailable until a managed renewal responder exists. Client/CA support and the earlier isolated proof do not constitute integration. It is not silently treated as HTTP-01.

AD server selection persists an inventory alias. The server resolves the alias to the inventory FQDN at read/save/run time and never trusts a posted arbitrary server name. A unique exact old FQDN can migrate to its inventory alias. A missing, renamed, incompatible or ambiguous host must be corrected by the administrator; another server is not silently substituted.

Saving changes never issues a certificate or unlocks the vault. Challenge switches cannot pass hidden credentials or stale listener authorization into a different method. Common issuance, validity, key matching, cleanup and rollback controls remain in force.

## Tests

Run npm test and npm run build in build/frontend. With Playwright available, run tests/certificate-form-browser.cjs against its local fixture server. The test checks inventory selection, assigned credential filtering, scheme-free CA input, method-specific payloads, disabled ALPN, no issuance on save, and desktop/phone layouts.
