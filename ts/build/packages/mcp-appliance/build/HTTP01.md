# HTTP-01 certificate validation

Settings > Certificates supports DNS-01 (including Active Directory) and HTTP-01.
HTTP-01 offers a native appliance responder or the existing external webroot.

The native responder binds TCP 80 only while an authorized request is running.
It serves only exact active hostname/token pairs beneath
`/.well-known/acme-challenge/`. It never exposes the console, directory listings,
private keys, arbitrary files, redirects, or write methods. Request concurrency
is bounded, sockets have timeouts, and published tokens expire after 15 minutes.
IPv4 and IPv6 listeners are separate. An occupied port causes failure without
stopping the existing service or opening the firewall.

Administrators must confirm reachability and authorize temporary access. By
default the firewall allowance is restricted to configured CA validator source
IPs/CIDRs. Public CA use requires an explicit any-source option; the directory
endpoint's address must not be assumed to identify public validation servers.
The client adds tagged rules and an expiring port set to the appliance nftables
chain, then removes only its own rules/set. On abnormal termination, the set
entry expires within 15 minutes; inert rule/set objects may need cleanup.
Upstream NAT, DNS records, and reverse proxies are not modified. All requested
names must resolve/reach this listener from the CA's network perspective.

A saved legacy HTTP configuration with confirmed external routing is migrated
to external mode, not silently converted to a listener. External mode starts no
server and changes no firewall rules. Wildcards remain DNS-01 only.

The CSR-only OpenSSL configuration is generated separately so missing host
policy include files do not break CSR generation. This does not disable HTTPS
certificate verification or change system cryptographic policies. RSA selection
explicitly uses 4096 bits; ECDSA remains available when accepted by the CA.

Saving settings does not request a certificate. HTTP needs no DNS credential.
Test-only issuance never installs the returned certificate. Normal installation
retains the existing exact-SAN/key validation and rollback checks.

References:
- RFC 8555, section 8.3: https://www.rfc-editor.org/rfc/rfc8555.html#section-8.3
- Dehydrated hook contract: https://github.com/dehydrated-io/dehydrated/blob/master/docs/examples/hook.sh

Tests: `npm test`, production build, and `tests/http-browser.cjs` with Playwright.
Browser tests use an isolated fixture server, not a real appliance.
