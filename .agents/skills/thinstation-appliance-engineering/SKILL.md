---
name: thinstation-appliance-engineering
description: Build portable ThinStation Docker- or K3s-backed appliance images. Use for package selection, offline container payloads, first-run setup, persistent storage, setup-docker/setup-k3s, buildtime/custom site configuration, package-owned runtime variable documentation, generated-secret boundaries, service-owned firewall rules, container image pinning, upgrade-safe immutable image design, and local QEMU qualification. Concrete application targets may be used only as reusable build examples, not deployment topology.
---

# ThinStation Appliance Engineering

Use ThinStation as an immutable appliance OS with mutable application state on explicit persistent storage.

## Core rules

- Keep application identity separate from deployment environment.
- Keep immutable compose/manifests/seeds in the image and copy them to persistent storage only after storage mounts.
- Mount persistent data before persistence services and container runtimes consume it.
- Make first-run installers rerunnable and non-destructive by default.
- Pin upstream application/container versions and stage disconnected images into the ISO when required.
- Validate fresh install, graceful shutdown, same-disk reboot, and EFI boot locally.
- Keep service-specific firewall ownership in the service package.
- Put portable non-secret site defaults in `thinstation.conf.buildtime`; use `/etc/thinstation.custom` for persistent local overrides.
- Whenever a package introduces a new ThinStation runtime/init variable, document it in that package's `build/conf/` contribution with purpose, accepted values, defaults, and security notes.
- Keep generated application secrets out of buildtime/custom configuration; create them at first run and persist them in application-owned state with restrictive permissions.
- Do not encode host inventories, private addresses, orchestration systems, or environment-specific repository relationships.

## References

- `references/persistence-and-setup.md` — generic state and first-run rules.
- `references/native-appliance-patterns.md` — ThinStation buildtime/config-writer/systemd patterns, immutable recovery, persistent runtime generations, update channels, registration UI, and hot-deploy development.
- `references/appliance-ci.md` — package selection, offline image staging, and standard build-pipeline mechanics.
- `references/firewall-and-server-packages.md` — package firewall ownership.
- `references/k3s-awx-appliance.md` — reusable K3s/AWX build mechanics.
- `references/wazuh-appliance.md` — reusable Wazuh build/validation mechanics.
