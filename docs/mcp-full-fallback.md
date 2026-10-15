# Immutable full MCP fallback

## Contract

Boot selection is: persistent active, persistent previous, pinned full MCP in the ISO, minimal rescue helper. Persistent generations retain the existing catalog install, activate and rollback workflow. No fallback code is copied into persistent active/previous slots automatically. A persistent update never modifies the bundled fallback; only a newly qualified ISO replaces it.

The bundled generation is version- and SHA256-pinned, not a moving latest catalog entry. Stage its application and complete virtualenv as unpacked files under `/usr/lib64/mcp-appliance/fallback` before ELF dependency collection. This lets the existing collector discover native extension dependencies such as `librt.so.1`. Preserve package licenses and provenance. Do not embed site credentials, inventory, connection identities or runtime logs in the payload.

Configuration, inventory, vault policy, credentials, connection identities and writable state remain in their existing persistent locations. Fallback does not unlock credentials or bypass the gateway. Code runs from the immutable payload with bytecode writes disabled and a writable persistent working directory. Configuration compatibility is required; a fallback cannot repair an incompatible or corrupt persistent configuration automatically.

Persistent generation quarantine and bundled fallback failure tracking are independent, even when their upstream build numbers are equal. Track bundled failures by artifact identity for the current boot, so a persistent build-309 quarantine does not reject a repaired ISO containing build 309. Repeated bundled startup failure selects the standard-library rescue helper; never loop indefinitely on the bundled server.

The UI must distinguish the configured persistent upgrade, selected/running generation, bundled fallback and minimal rescue. A healthy bundled default is usable without first downloading an upgrade. Fallback after a failed upgrade needs an explicit diagnostic, not a misleading indication that the installed upgrade is running.

## Qualification

A version is a candidate, not known-good, until checked against the appliance image. Verify archive checksum and source identity; reject unsafe paths, special files and escaping links during extraction. Validate native imports and import the real application; `py_compile` alone is insufficient. Run a local MCP initialize and tools/list handshake with isolated scratch configuration, no credentials and no infrastructure tool calls. Validate ELF dependencies after image finalization. Preserve the results with the ISO.

Before production rotation, boot-test a disposable VM with a blank persistent disk, healthy active generation, rejected active with healthy previous, both persistent slots failed, and failed bundled runtime. Verify identical connection configuration is retained and normal catalog upgrades/rollback still work. A successful process start is not a protocol health check.

## Initial candidate

The published build-309 artifact is available for qualification:

- Generation: `thinstation-mcp-build-309`
- Source commit: `cdea977dbe9f10a54abfb2c93ab8238e55567fd4`
- Archive SHA256: `3f01f375b8190f1640f8a036551a0883a36eb0f0778fe23cb5c8d2f16da394bd`

Its failure on the existing ISO was an absent native system library. This does not establish that it is qualified on a replacement ISO; the checks above are still required.
