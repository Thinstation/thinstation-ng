---
name: thinstation-appliance-engineering
description: Build and validate ThinStation immutable infrastructure appliances. Use for Docker- or K3s-backed appliances, Wazuh, AWX, GitLab EE, NPM, setup-docker/setup-k3s, persistent storage, offline container images, first-run installers, appliance CI, firewall contributions, upgrades, and reboot/persistence behavior.
---

# ThinStation Appliance Engineering

Use ThinStation as an immutable appliance OS with mutable application state on explicit persistent storage.

## Core rules

- Keep immutable compose/manifests/seeds under `/usr/lib/thinstation/docker-stacks/<stack>/`; copy them to persistent `/docker/<stack>/` after storage mounts.
- Mount persistent data before persistence services, containerd, Docker, or K3s consume it.
- Make first-run installers rerunnable and non-destructive by default.
- Pin upstream application/container versions and stage disconnected images into the ISO when the appliance must install without network pulls.
- Validate fresh install, graceful shutdown, same-disk reboot, and EFI boot.
- Keep service-specific firewall ownership in the service package.

## References

- `references/persistence-and-setup.md` — generic Docker appliance state and first-run rules.
- `references/appliance-ci.md` — CI/package selection and offline image staging.
- `references/firewall-and-server-packages.md` — package firewall ownership.
- `references/k3s-awx-appliance.md` — K3s/AWX architecture.
- `references/wazuh-appliance.md` — validated Wazuh 4.14.8 appliance pattern and failure modes.
