# Firewall and Server Package Contributions

## Design

ThinStation's server-package firewall model is still valid with nftables.

The `firewalld` package installs a startup hook at `/etc/init.d/firewall`. On firewalld startup it:

1. sources every `/etc/firewall.d/*` fragment
2. lets those fragments call `firewall-cmd`
3. calls `firewall-cmd --runtime-to-permanent`

The live appliance uses firewalld with:

```text
FirewallBackend=nftables
```

Therefore package fragments should use `firewall-cmd`, not direct nft or legacy iptables rules. Firewalld owns backend translation.

## Existing package examples

The established convention is package-owned firewall requirements:

- `cups/build/extra/etc/firewall.d/80cups` adds IPP services
- `lighttpd/build/extra/etc/firewall.d/65lighttpd` adds HTTP
- `tftpd/build/extra/etc/firewall.d/65tftp` adds TFTP
- `sssd/build/extra/etc/firewall.d/30sssd` adds Kerberos, LDAP/LDAPS, Global Catalog ports, and Samba client

Keep generic setup/configuration scripts firewall-agnostic. A service package should contribute the ports/services it needs.

## Metadata-only appliance packages

GitLab EE and NPM are not normal RPM-backed ThinStation packages. They have effectively empty `.dna` files and no standard `build/install` path that invokes `repackage`.

For these packages, use `build/finalize` to create runtime firewall fragments directly in the final image.

Current GitLab finalizer must create:

```text
/etc/firewall.d/70gitlab-ee
```

with:

```bash
firewall-cmd --add-service=http
firewall-cmd --add-service=https
firewall-cmd --add-port=2222/tcp
```

Current NPM finalizer must create:

```text
/etc/firewall.d/70nginx-proxy-manager
```

with:

```bash
firewall-cmd --add-service=http
firewall-cmd --add-service=https
firewall-cmd --add-port=81/tcp
```

## Docker/firewalld coexistence

Docker creates its own bridge/forwarding rules and firewalld may create a `docker` zone/policy. Avoid replacing this with handcrafted nftables rules unless debugging proves firewalld/Docker integration is the actual fault.

Debug in layers:

1. `ss -lntp` on the host
2. `docker port <container>`
3. `firewall-cmd --get-active-zones`
4. `firewall-cmd --zone=public --list-services --list-ports`
5. `nft list ruleset`
6. service listeners inside the container

A host port can be correctly DNATed/accepted by nftables while the container still returns connection refused because its internal service is not ready.

## Port ownership rule

Do not let container service ports collide with appliance-management ports.

For GitLab appliances:

- appliance/MCP SSH owns host TCP 22
- GitLab repository SSH owns host TCP 2222
- GitLab HTTP/HTTPS own TCP 80/443

Keep the compose mapping, the application-advertised port, and firewall contribution synchronized.
