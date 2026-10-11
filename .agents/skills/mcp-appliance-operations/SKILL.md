---
name: mcp-appliance-operations
description: Operate, update, troubleshoot, and qualify an immutable ThinStation-based MCP appliance. Use for MCP runtime generations, recovery and ISO rotation, credential broker authorization, persistent chroot environment jobs, registration and connections, health checks, deployment rollback, and operational release gates.
---

# MCP Appliance Operations

Treat the immutable ISO as recovery and baseline OS; keep active MCP generations, secrets, and mutable environments on explicit persistent storage.

## Operational workflow

1. Establish current release, active generation, persistent storage, connection state, and service health before making changes.
2. Confirm credential host, scope, lease, and execution-context authorization independently. Never expose secrets in logs or user-visible output.
3. Prefer staged, reversible updates over in-place overwrites. Do not automatically copy recovery code into an active generation.
4. Use atomic activation, health checks, and a preserved previous generation for rollback.
5. For environment rebuilds, verify source trust, package manager isolation, cleanup of temporary mounts, and actual installed packages.
6. When rotating an ISO, distinguish rotation alone from rotation plus cold boot; explicitly select one and check the resulting guest.
7. Validate UI state against real services, and ensure failed credential/ACME operations return actionable feedback.
8. Report separately what was changed, deployed, rebooted, and tested. Do not report a push or build as deployment success.

## References

- `references/vault-and-connectivity.md` for vault resolution, SSH agents, and connections.
- `references/generations-and-environments.md` for activation/recovery and chroot environments.
- Use the `thinstation-appliance-engineering` skill for package/ISO implementation, and `thinstation-boot-validation` for QEMU qualification.
