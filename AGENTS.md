# ThinStation NG agent guidance

ThinStation NG is an image-building system with a generated chroot and package-root workflow. Keep changes reusable, portable, and free of site-specific deployment assumptions.

## Repository rules

- Use focused branches and merge requests for source changes.
- Treat `ts/build/packages/*/build/extra`, package metadata, profiles, and scripts as source; package-root copies created by unwind/repackage are generated unless the package intentionally owns them as source.
- Do not broad-reset or broad-clean an initialized build checkout.
- Do not run `setup-chroot -c` merely to make `git status` cleaner. It can remove completed build outputs and interrupted cleanup can leave dangerous bind mounts/stage markers.
- Preserve ISO/output and expensive staged container payloads before destructive build cleanup.
- Keep site-specific organization names, addresses, credentials, deployment topology, and environment-only values out of reusable source and AI guidance.
- Do not suppress build warnings with broad text filters. Known benign output should remain visible so future meaningful failures are not hidden.
- Prefer Fedora/upstream RPMs and prebuilt artifacts for normal ThinStation builds. Regular users should not need to compile application software merely to build an image.
- In-tree source compilation is acceptable while a package is under active development, when it materially speeds iteration, and for unavoidable kernel-coupled components such as proprietary kernel modules. Treat these compile paths as development tooling rather than the long-term user-facing package path.
- Once a customized package is stable enough for normal use, move its source build/patch workflow to the dedicated `thinstation-rpms` repository and have ThinStation NG consume the resulting RPM.
- Development harnesses used to create a custom package (for example the former iPXE source-build experiments) should be retired from ThinStation NG once the external package pipeline is authoritative. Keep regression tests that validate ThinStation's package consumption, image assembly, or runtime behavior.

## Project skills

Canonical reusable agent skills live under `.agents/skills/`.

- `.agents/skills/thinstation-ng-engineering/` — turn a target definition into ThinStation configuration, build it, review source/generated state, and prepare a qualified change.
- `.agents/skills/thinstation-appliance-engineering/` — build portable Docker/K3s-style ThinStation appliance images and persistent first-run behavior.
- `.agents/skills/thinstation-boot-validation/` — validate images locally with `bt`, QEMU, QGA, BIOS/UEFI/Secure Boot, PXE, fastboot, and persistent disks.

Use only repository-local tools and generic local QEMU validation unless the task explicitly provides some other environment.
