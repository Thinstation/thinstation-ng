# Build Architecture

## Source vs active build tree

The most important distinction in this repo:

- `ts/build/conf/boot2docker/*` is a reusable template/profile.
- CI copies that profile into the active build tree with `cp -a /build/conf/boot2docker/* /build/.`.
- `setup-chroot -e stb` parses active `ts/build/build.conf`, `ts/build/thinstation.conf.buildtime`, and related active files.

Do not diagnose an active build by looking only at the profile template. Do not commit active/generated profile edits unless they are intentionally becoming source defaults.

## setup-chroot and install_chroot

`setup-chroot` chroots into the repository root. Inside the chroot:

- repository root is `/`
- `ts/build` is `/build` via a symlink created by `install_chroot`
- `TSWRKNG=/ts/build`

This path model matters when passing build parameters that point to files. A file created at repository root before entering the chroot is `/filename`, not `/build/filename`.

`install_chroot` uses environment-driven tuning:

- `DIST_VER`, default 44
- `MAX_PARALLEL_DOWNLOADS`
- `MAX_DOWNLOADS_PER_MIRROR`
- `TS_EXTRA_PORTS` for CI-specific RPM preload packages

CI currently uses 20 parallel downloads and 20 per mirror for appliance builds. Keep large preload lists in CI policy, not `ts/rpms/other`. `ts/rpms/other` should retain only standing/global dependencies such as `python3-pyside6` unless there is a real repository-wide reason.

## Build cleanup and generated state

Do not use `setup-chroot -c` casually as a source-diff cleanup command.

Important behavior established during appliance work:

- `setup-chroot -c` can remove generated boot output, including a completed ISO. Preserve any ISO or staged payload that matters before cleaning.
- Cleanup is two-stage and can leave `cleanstage2` or bind mounts behind if interrupted.
- Never recursively remove chroot paths until confirming no host bind mounts remain below them. A mounted `/run`, `/proc`, `/sys`, or `/dev` can turn an apparent chroot cleanup into deletion of live host runtime state.
- A chroot is considered initialized by `setup-chroot` when repository-root `bin/bash` exists. A half-populated chroot can therefore be mistaken for a valid one.
- A stale `dostage2` marker can cause stage 1 to be skipped even when `bin/bash` is absent.

Prefer targeted inspection first. If a truly fresh chroot is required, preserve outputs, unmount chroot bind mounts, remove stale stage markers, and then use the normal bootstrap path. Do not broad-`git clean` source trees.

## Fastboot model

- `ts/build/tmp-tree` is the early initrd/root filesystem.
- `ts/build/fastboot-tmp` is deferred payload later packed into `lib.squash`.
- Runtime becomes a composite filesystem.

When validating a fastboot build, inspect both trees. Early boot consumers cannot depend on libraries that exist only in `fastboot-tmp`.

`fastboot/fastboot-mangle` has been refactored to:

- use policy files such as `lib-boot`, `bin-boot`, `etc-ro`, `lib-rw`, `usr-rw`
- compute recursive dependency closure for libraries that are actually retained
- avoid fragile `ls | grep` style plumbing where possible
- use per-process scratch directories rather than shared `/tmp/fastlib*`

A prior systemd/libbpf warning was fixed by retaining recursive dependencies for an explicitly retained `libbpf.so.1` (`libelf`, `libz`, `libc`, `libzstd`, etc.). Preserve the rule: recurse only from libraries actually retained.

## Refactoring discipline

The build system is mature shell with substantial implicit state, sourced variables, path assumptions, and side effects. Treat broad cleanup as a separate engineering project, not as incidental work while fixing a functional issue.

Apply these rules:

- Prefer the smallest change that resolves a demonstrated problem.
- Do not rewrite or decompose `ts/build/build` merely because it is difficult to read.
- Extract a section only when there is a concrete payoff such as isolation for testing, repeated defects, or a clear interface boundary.
- For mechanical extractions, preserve behavior exactly and validate a representative full build before accepting the change.
- Keep diagnostic tooling and validation when they improve observability even if a larger refactor is abandoned.
- Stop an exploratory refactor when the risk or blast radius grows faster than the operational benefit.
- Separate functional fixes from cleanup so either can be reverted or omitted independently.

The preferred outcome is often better understanding and better tests rather than cleaner-looking shell.

## Other established build behavior

- Kernel debug console is configurable with `param debugconsole`; absence means normal non-debug builds use `console=tty1`.
- The nftables package finalizer explicitly selects nft-backed `iptables`, `ebtables`, and `arptables` alternatives.
- Avoid reintroducing explicit CI `dnf install ... docker` bootstrap lines. Docker-backed appliance builds use normal chroot/package machinery.


## Package metadata contract

Every package directory under `ts/build/packages/` must contain all four metadata files:

- `.dna`
- `.wind`
- `.unwind`
- `dependencies`

This remains true for packages that are mostly static source, packages repackaged from RPMs, and packages whose `.dna` is intentionally empty.

`.dna` is the source description consumed by `ts/bin/update`. `ts/bin/clean_chroot` generates or refreshes `.wind` and `.unwind` from that `.dna`; do not treat the cache files as independent source of truth. If `.dna` changes, regenerate the caches through the normal tooling rather than hand-maintaining divergent commands.

An empty `.dna` is valid. Its generated cache files still exist and contain the MD5 header for the empty file. Repackaged RPM content can be handled by `build/install` and `build/remove` while the mandatory package metadata remains present.

## Static package files vs .dna

Do not add static package-owned source files to `.dna` just to make them visible.

ThinStation package directories can contain static runtime content directly. If a file is authored and maintained as part of the package itself, place it directly under the package tree at its intended runtime path, for example:

```text
packages/base/etc/sysctl.d/20-thinstation-hardening.conf
```

Files not listed in `.dna` are mostly ignored by the update/RPM-refresh machinery, which is desirable for static source that should remain exactly as maintained in Git.

Use `.dna` for files that the package update mechanism manages, imports, links, or refreshes from RPM/package sources. Do not list ordinary static package content there unless there is a specific update-system reason. The rule that `.dna` itself must exist is separate from whether a particular static file belongs in it.
