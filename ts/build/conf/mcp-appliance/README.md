# ThinStation MCP Appliance

Ultra-minimal immutable MCP appliance profile derived from `conf/tiny`.
The immutable image contains only boot, networking, SSH/recovery, TLS,
persistence tooling, Python runtime, and VM guest integration.

Mutable configuration and runtime environments live on the persistent volume.
Foreman or ordinary upstream repositories will provide package content for
runtime environments without modifying the base image.

Certificate support defaults to the lightweight `dehydrated` package. The
`lego` package remains available as an alternate ACME client. Optional
`mcp-appliance-sssd` support is planned for domain authentication.
