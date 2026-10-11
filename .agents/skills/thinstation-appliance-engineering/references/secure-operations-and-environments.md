# Secure operations and disposable environments

## Credential brokering
- Distinguish credential existence, unlock/lease status, protocol scope, allowed target host, and the actual execution environment. A credential can be unlocked but forbidden for the requested host.
- Prefer an auditable broker/provider interface that delivers credentials only to the intended operation. Never log, echo, store in command history, or embed credentials in an image or repository.
- Bootstrap-only secrets needed to reach a central vault must survive restart under explicit tightly scoped local policy. Do not require manual intervention for unattended dependent services.
- SSH-agent sockets are session-specific. An agent available in a user's terminal is not necessarily available to an MCP remote command. Test authentication from the same execution context as the operation.
- Keep provider selection independent from target inventory; a local credential store is one provider, not the only supported provider.

## Chroot environment lifecycle
- Keep environments in dedicated persistent storage separate from the immutable recovery root and disposable workspace.
- Stage new environments away from the active one, validate, then atomically activate only after successful install and mount cleanup; retain rollback.
- Bootstrap distro trust before using internal mirrors: provision the approved CA, install signed APT keyrings, and isolate approved DNF repos by distro/release.
- Support Fedora/Rocky through RPM/DNF and Ubuntu through debootstrap/APT without pretending an incomplete bootstrap is successful.
- Track and detach temporary proc/sys/dev/run and resolver mounts before finalizing or deleting a chroot. Treat already-unmounted mounts as clean; retry transient busy unmounts with bounds and stop staged GPG/packaging helpers before teardown.
- Surface failed jobs accurately and report installed packages from verification rather than inferred manifests.
