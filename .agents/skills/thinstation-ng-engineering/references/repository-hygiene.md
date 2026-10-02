# Repository hygiene and initialized chroots

## Source versus generated content

A ThinStation package may contain authored files under `build/extra`, metadata such as `.dna`, `.wind`, `.unwind`, and dependencies, plus generated package-root files created during unwind/repackage.

Do not use `git status` alone to decide what should be committed after a build. Compare intended source paths and the branch diff against canonical GitLab.

## Cleanup hazards

- `setup-chroot -c` can remove generated ISO/output. Preserve valuable output first.
- Cleanup can be multi-stage. Interrupted cleanup can leave `cleanstage2`, `dostage2`, or bind mounts behind.
- Never recursively delete a chroot directory until `mount`/mountpoint checks prove host bind mounts are detached.
- `setup-chroot` treats repository-root `bin/bash` as evidence the chroot exists. A partial chroot can therefore skip bootstrap.
- A stale `dostage2` can skip stage 1 even when the chroot is absent.
- Package `.wind/.unwind` caches are tracked source metadata in this repository. Do not globally delete them to force rebuilds.

## Adding new build/extra files to an already-unwound package

An incremental build may not automatically merge newly-added `build/extra` files into an already-populated package root. Confirm the intended runtime files exist in the package root or final image before declaring the build valid.

If a focused package refresh is needed, use the repository's package population/merge semantics rather than broad source cleanup. During development, a hardlinked `cp -al build/extra/. package-root/` can mirror the package merge semantics for a targeted validation, but the committed source remains under `build/extra`.

## Expensive appliance payloads

Offline Docker image archives staged under the ISO tree can be several gigabytes and expensive to regenerate. Treat them as generated output, not Git source, but preserve/copy them before cleanup when doing iterative appliance work.
