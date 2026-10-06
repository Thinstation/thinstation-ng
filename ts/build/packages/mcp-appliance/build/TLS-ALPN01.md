# Managed TLS-ALPN-01

The Certificates form, validator, issue/renew worker, forced requests and test-only
mode support TLS-ALPN-01. Dehydrated generates per-name challenge certificates;
a temporary native Python/OpenSSL responder validates their SAN, critical
acmeIdentifier digest, validity and matching private key before publishing them.

The responder binds TCP 443 only during a request and requires the exact active
SNI hostname plus the sole ALPN acme-tls/1. Bounded ClientHello routing checks
precede the standard OpenSSL TLS 1.2/1.3 handshake. No HTTP application data,
management endpoints, default certificate or TLS session tickets are served.
Unknown names, inactive challenges and non-ACME protocols fail closed.

The configured validator IPs/CIDRs restrict the temporary nftables rule. Public
validation requires explicit opt-in. The firewall service-port set expires after
15 minutes even following a hard kill. Normal completion, failures and SIGTERM
stop the listener and remove challenge keys and firewall objects. Expired empty
firewall objects may remain after SIGKILL but cannot continue permitting access.
The management service on port 8443 and any existing port-443 service are never
stopped. A port conflict fails the request before the firewall is changed.

Only DNS identifiers are supported by the managed form. Wildcards require DNS-01.
Upstream NAT must route TCP 443 and any proxy must pass TLS through without
terminating it. HTTP redirects cannot carry this validation. IPv4 and IPv6
listeners are provided when available. The CA API always uses verified HTTPS,
independently of the selected challenge transport. No vault credential is used
by TLS-ALPN-01. Test-only mode never installs the issued management certificate.

The code is site-independent: names, sources, CA and other choices come from the
saved configuration. No test-host address is compiled into the responder.

References: RFC 8737 sections 3-5; Python ssl MemoryBIO documentation.
