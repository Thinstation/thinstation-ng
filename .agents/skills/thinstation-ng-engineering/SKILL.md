---
name: thinstation-ng-engineering
description: Engineer the ThinStation Next Generation repository safely. Use for setup-chroot/install_chroot, package metadata and build/extra behavior, source-vs-generated file questions, build profiles, usr-merge/fastboot build mechanics, cleanup/recovery, repository hygiene, and making or reviewing source changes in davinci/thinstation-ng.
---

# ThinStation NG Engineering

Work from canonical GitLab `davinci/thinstation-ng` and current `7.4-Stable`.

## Workflow

1. Inspect canonical source before changing the build host.
2. Identify whether a path is authored source, active build configuration, generated package-root content, or build output.
3. Make the smallest reusable source change on a focused branch.
4. Avoid broad cleanup/reset operations on a live initialized chroot.
5. Validate with the cheapest test that proves the change, then use full integration build when required.
6. Commit only source and intentional metadata; leave generated unwind/build content unstaged.
7. Merge through an MR.
8. When a durable rule is learned, update the appropriate skill/reference.

## References

- Read `references/build-architecture.md` for chroot paths, build phases, package metadata, fastboot build split, and cleanup traps.
- Read `references/repository-hygiene.md` before cleaning an initialized build workspace or interpreting a dirty package tree.
