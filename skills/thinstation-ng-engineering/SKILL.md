---
name: thinstation-ng-engineering
description: Engineering guide for the ThinStation Next Generation repository and lab workflow. Use when working on the thinstation-ng repo, ThinStation build system, install_chroot/setup-chroot, fastboot, Docker-backed appliance ISOs, GitLab CI appliance builds, package manifests/finalizers, persistent-files, setup-docker, PVE/QEMU validation, or debugging a built ThinStation appliance. Encodes repo conventions, source-vs-generated file distinctions, branch/MR workflow, and known lab validation patterns.
---

# ThinStation NG Engineering

Work from the canonical GitLab project `davinci/thinstation-ng` on branch `7.4-Stable` unless the user explicitly says otherwise.

## Operating rules

- Treat GitLab as source of truth. Use a feature branch, commit logically related changes, open an MR, review the diff, then merge.
- Prefer the GitLab Self-Managed connector for canonical source changes. The Fedora workspace at `/thinstation-ng` may be stale, generated, or intentionally dirty.
- Never broadly reset or clean the Fedora workspace. `./setup-chroot -c` is the approved way to remove most build artifacts when inspecting real diffs.
- Distinguish templates from the active build tree. CI copies `ts/build/conf/boot2docker/*` into `ts/build/`; `setup-chroot -e stb` parses the active files under `ts/build/`.
- Keep organization/site specifics out of reusable source. Supply them through CI variables, environment variables, surveys, or extra vars.
- For appliance-specific behavior, prefer CI/package selection over globally changing the shared boot2docker profile.
- Let server packages declare their own firewall requirements through `/etc/firewall.d`; keep generic setup scripts firewall-agnostic.
- Validate source changes in the real pipeline and, when relevant, boot the produced ISO in PVE and inspect the live guest.

## Read the relevant reference

- For repo structure, build phases, active/template config rules, `install_chroot`, and package metadata rules: read `references/build-architecture.md`.
- For the fastboot build/runtime handoff, loader selection, service ordering, and failure diagnostics: read `references/fastboot-runtime.md`.
- For GitLab CI, appliance package selection, Docker image export, compose payloads, and CI variables: read `references/appliance-ci.md`.
- For firewalld, nftables, `/etc/firewall.d` package contributions, and server-package port ownership: read `references/firewall-and-server-packages.md`.
- For `persistent-files`, immutable appliance state, `setup-docker`, first-run configuration, and idempotency: read `references/persistence-and-setup.md`.
- For PVE, QGA/SSH validation, lab aliases, and efficient debugging: read `references/lab-validation.md`.
- For iPXE, BIOS/UEFI/Secure Boot, `bt` test modes, OVMF RNG requirements, persistent runner labs, and fast diagnostic iteration: read `references/boot-and-test-architecture.md`.

## Change workflow

1. Inspect canonical `7.4-Stable` before editing.
2. If the issue was found on Fedora, clean generated artifacts with `sudo ./setup-chroot -c` before deciding what is a source diff.
3. Create a focused branch from current `7.4-Stable`.
4. Make the smallest reusable fix. Avoid one-off lab values in source.
5. Review the branch diff against `7.4-Stable`.
6. Merge through an MR, unless the user explicitly requested direct commits to the active stable branch.
7. Use the fastest valid test first: focused direct execution in the persistent runner lab, then the smallest relevant build, then full CI only for integration/final validation.
8. Reuse initialized chroots and generated boot trees when the test does not require regeneration. Do not repeatedly unwind/reinitialize the build environment for firmware/QEMU/parser experiments.
9. If the output is an appliance ISO, publish it, boot it in PVE, and verify the behavior from the live guest.
10. If new non-obvious behavior or a recurring trap is discovered, update this skill in the same repo.
