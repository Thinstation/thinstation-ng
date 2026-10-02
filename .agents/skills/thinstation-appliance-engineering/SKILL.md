---
name: thinstation-appliance-engineering
description: Build portable ThinStation Docker- or K3s-backed appliance images. Use for package selection, offline container payloads, first-run setup, persistent storage, setup-docker/setup-k3s, service-owned firewall rules, container image pinning, upgrade-safe immutable image design, and local QEMU qualification. Concrete application targets such as Wazuh, AWX, GitLab EE, or NPM may be used only as reusable build examples, not deployment topology.
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
- Do not encode host inventories, private addresses, orchestration systems, or environment-specific repository relationships.

## References

- `references/persistence-and-setup.md` — generic state and first-run rules.
- `references/appliance-ci.md` — package selection, offline image staging, and standard build-pipeline mechanics.
- `references/firewall-and-server-packages.md` — package firewall ownership.
- `references/k3s-awx-appliance.md` — reusable K3s/AWX build mechanics.
- `references/wazuh-appliance.md` — reusable Wazuh build/validation mechanics.
