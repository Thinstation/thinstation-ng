# Vault and connectivity

A secret's existence, unlock state, authorized protocols/scopes, allowed hosts, and availability in a particular session are independent checks. The target for an authenticated operation must be allowed before materialization.

Use provider-neutral credential resolution. Local bootstrap secrets should be narrow, persistent, and accessible after unattended reboot where required to reach a central broker; general service credentials should remain brokered and auditable.

Do not assume interactive SSH agents are forwarded to automated SSH/MCP execution. Test the actual execution context. Never use insecure SSH host-key settings merely to make a push work.

Separate LAN-addressable MCP endpoints from cloud/tunnel registration in status, security assumptions, and support procedures. UI states must reflect actual connector/runtime availability rather than catalog presence.
