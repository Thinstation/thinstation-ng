# Active Directory DNS provider

Choose DNS-01 and Active Directory DNS in Settings > Certificates. Configure the canonical hostname of a domain controller serving DNS, the AD-integrated zone and the full Kerberos realm. Use the server named as primary in the zone SOA record, not an IP or alias. No domain join, unsigned-update fallback or custom hook is required.

Select an Active Directory vault credential containing domain, username and password. Its domain must match the realm. The credential needs the acme scope and, when its allowed hosts are restricted, the canonical DNS-server hostname must be listed explicitly. Every use, including the connection test, requires an authorized lease or one-shot grant. The provider never unlocks the vault or grants itself access.

Test AD connection authenticates, obtains a DNS service ticket and queries the authoritative zone. It does not change DNS, request a certificate, or prove record-write permission. Saving is also separate from issuance.

Delegate the service account only the necessary challenge record permissions. Precreating the intended _acme-challenge record nodes and assigning their ACLs avoids broad zone-creation rights. Domain Admin membership is not required. The appliance does not modify AD ACLs.

The initial provider supports one zone, a DC serving both DNS and Kerberos, password-based AD credentials and names in the saved certificate order. It does not support cross-realm credentials, multiple-zone orders or CNAME/DNAME challenge delegation. Wildcards use the normal non-wildcard challenge owner.

Updates add one TXT value; cleanup deletes that exact value only. Existing and unrelated TXT values are preserved. Cleanup is retried after validation failure before the private Kerberos ticket cache is removed. Unresolved cleanup markers remain under state/acme-needs-cleanup-* for administrator review. A process crash or forced kill can still leave a TXT value behind; DNS TTL does not delete records.

Tickets are short-lived and non-forwardable, in a private /run directory. Passwords go to kinit through standard input, not argv or environment. Automatic renewal still requires vault authorization at the time it runs.

Propagation checks cover the selected authoritative server, not every replica or the CA resolver. The CA must see that DNS view; internal-only AD records cannot satisfy public CA validation. DNS/Kerberos connectivity and synchronized clocks are prerequisites.

The native ad-dns-tools package uses the existing repackage workflow and retains licenses. Preload bind-utils and krb5-workstation with the appliance RPMs to avoid late downloads. Revisit runtime dependencies when changing the distribution. Run npm test and npm run build in the frontend directory. Mocked tests do not prove a live account's DNS rights; verify issuance and cleanup separately with the intended CA and a least-privileged account.
