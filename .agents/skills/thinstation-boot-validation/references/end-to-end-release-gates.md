# End-to-end release and recovery qualification

A green image build is not proof of a functional deployment.

Exercise distinct gates: (1) source and CI build, (2) publish with immutable artifact identifier, (3) install/rotate on a disposable guest, (4) boot services and connector, (5) persistent configuration and credentials, (6) shutdown/reboot on the same disk, (7) update with rollback, and (8) immutable recovery if activation fails.

For MCP appliances additionally check runtime status, web UI status/control semantics, outbound connection/registration, vault bootstrap availability, and representative environment rebuilds. Record which checks ran and their outcomes; do not claim complete qualification from a successful publish or healthy process alone.

Do not embed environment-specific FQDNs, addresses, internal CA endpoints, or inventory in the reusable skill or image. Local tests should cover generic contracts; lab deployment can provide additional evidence.
