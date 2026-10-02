# ThinStation NG agent guidance

ThinStation NG is an image/appliance build system with a generated chroot and package-root workflow. Keep changes reusable and keep generated build state out of commits.

## Repository rules

- Canonical branch: `7.4-Stable`. Use focused branches and merge requests for source changes.
- Treat `ts/build/packages/*/build/extra`, package metadata, profiles, and scripts as source; package-root copies created by unwind/repackage are generated unless the package intentionally owns them as source.
- Do not broad-reset or broad-clean a working build checkout.
- Do not run `setup-chroot -c` merely to make `git status` cleaner. It can remove completed build outputs and interrupted cleanup can leave dangerous bind mounts/stage markers.
- Preserve appliance ISO/output and expensive staged container payloads before any destructive build cleanup.
- Keep site-specific organization names, addresses, credentials, and lab-only values out of reusable source.
- Do not suppress build warnings with broad text filters. Known benign output should remain visible so future meaningful failures are not hidden.

## Project skills

Canonical reusable agent skills live under `.agents/skills/`.

- `.agents/skills/thinstation-ng-engineering/` — repository architecture, package/build mechanics, chroot hygiene, and safe source changes.
- `.agents/skills/thinstation-appliance-engineering/` — Docker/K3s appliances, persistence, offline container payloads, Wazuh/AWX patterns, CI and firewall ownership.
- `.agents/skills/thinstation-boot-validation/` — fastboot, QEMU/`bt`, BIOS/UEFI/Secure Boot, QGA, and persistent-disk validation.

Load only the skill relevant to the task. See `.agents/README.md` for the publishing/discovery convention.
