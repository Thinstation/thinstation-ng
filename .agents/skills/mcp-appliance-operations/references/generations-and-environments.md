# Runtime generations, recovery, and environments

Keep a bootable immutable recovery runtime distinct from activated persistent MCP generations. Stage and verify a generation, activate it explicitly, and preserve a rollback target. Never silently promote recovery payloads into the active slot.

For rotation, record target ISO, boot mode, whether a cold boot is requested, active VM/disk identity, and post-boot service/registration state. An ISO publication, VM reboot, and runtime activation are separate milestones.

Build persistent Linux environments with distro-specific tooling and explicit signed repository policy. Provision internal CA trust before mirror access. Stage new roots, perform bounded mount cleanup, validate package installation, then activate. Do not delete a root while host mounts remain attached.

Qualification should test fresh install, reboot, update, rollback, recovery, and representative supported distro roots; report untested cases explicitly.
