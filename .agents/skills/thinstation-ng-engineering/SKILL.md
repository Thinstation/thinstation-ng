---
name: thinstation-ng-engineering
description: Turn a server, desktop, kiosk, or appliance target definition into a qualified ThinStation NG image. Use for choosing packages and machine profiles, creating or modifying build.conf/thinstation.conf inputs, setup-chroot/install_chroot, package metadata/build/extra behavior, source-vs-generated files, building images, debugging build failures, qualification, and preparing a branch/MR for the standard project pipeline.
---

# ThinStation NG Engineering

Accept the desired **target** first, then derive the repository changes needed to build and qualify it.

## Target-to-image workflow

1. Normalize the target definition: purpose, hardware/virtual platform, boot modes, packages/services, UI/session, network needs, persistence, storage, security constraints, and required output format.
2. Inspect existing profiles and packages before inventing new ones.
3. Choose or create the smallest appropriate configuration under `ts/build/conf/`; keep common behavior in reusable packages rather than duplicating profile logic.
4. Add/update package source under `ts/build/packages/` when the target needs new runtime files, dependencies, finalizers, kernel modules, or first-run behavior.
5. Activate the intended profile/config in the build tree.
6. Initialize or reuse the chroot safely and build the image.
7. Test locally with the repository's QEMU/`bt` tools using the smallest matrix that covers the target.
8. Debug from concrete build/runtime evidence; fix source, rebuild only what changed, and repeat.
9. Qualify the target against its declared requirements, including reboot/persistence or EFI/Secure Boot when applicable.
10. Review the source diff versus generated state, commit only intentional source, and submit through the repository's normal branch/MR/CI workflow.

## References

- Read `references/target-definition.md` for the input contract and how to translate it into profile/package choices.
- Read `references/build-architecture.md` for chroot paths, build phases, package metadata, fastboot build split, and cleanup traps.
- Read `references/repository-hygiene.md` before cleaning an initialized workspace or interpreting a dirty package tree.
- Use the `thinstation-boot-validation` skill for local runtime qualification.
