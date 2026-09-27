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

## Build cleanup

Use:

```bash
sudo ./setup-chroot -c
```

before assessing Fedora workspace diffs. This removes most generated build artifacts and makes source changes visible without a destructive `git clean` or reset.

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

## Other established build behavior

- Kernel debug console is configurable with `param debugconsole`; absence means normal non-debug builds use `console=tty1`.
- The nftables package finalizer explicitly selects nft-backed `iptables`, `ebtables`, and `arptables` alternatives.
- Avoid reintroducing explicit CI `dnf install ... docker` bootstrap lines. Docker-backed appliance builds use normal chroot/package machinery.
