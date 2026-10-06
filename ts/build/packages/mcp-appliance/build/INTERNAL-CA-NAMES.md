# Internal ACME names and appliance defaults

Select Internal CA to explicitly permit a valid single-label DNS identifier in the primary name or SAN list. Other ACME CA and the built-in public profiles continue to require fully qualified names. Known Let's Encrypt endpoints cannot be marked internal. HTTPS CA trust checking is unchanged.

A fresh unsaved form seeds its primary name from the configured appliance hostname. A short system hostname is combined with its sole configured DNS search suffix. No reverse-DNS lookup is performed and no domain is guessed when search domains are missing or ambiguous. Saved values, including an explicitly empty value, are not overwritten. The Use appliance FQDN button restores the current known default on demand. Seeding never saves, grants credentials, or issues a certificate.

Short names are literal certificate identifiers: `mcp` is not silently rewritten to `mcp.example.test`. Internal CA policy and its resolver must support the requested name. To support both access forms, request the full name and add the short name as a SAN.

HTTP-01 uses the literal Host name; TLS-ALPN-01 uses the literal requested SNI name and exact challenge SAN. Post-issuance validation checks the exact requested SAN set including short names. Public-mode short names, IP addresses, malformed labels, loopback identifiers, and short-name wildcards remain rejected.

For AD DNS-01 a short identifier is mapped to `_acme-challenge.<short>.<configured-zone>.` inside the already-selected authoritative zone; no record outside that zone is permitted. The internal validator must apply that same DNS search suffix. A validator performing only absolute `_acme-challenge.<short>.` lookups will not find the scoped record; use HTTP/TLS validation or FQDN-only names in that case. This compatibility behavior is not asserted to work with every ACME CA. AD DNS server, zone and Kerberos realm remain fully qualified and inventory-bound.

Regression qualification includes normalization, internal/public separation, hostname discovery, saved-value preservation, real TLS 1.2/1.3 short-name handshakes with generated fixture certificates, exact SAN validation, and a browser fixture using real save/readback for all three challenge types. No external CA order or live DNS change is required by these tests.
