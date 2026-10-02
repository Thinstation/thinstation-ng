# Fastboot Runtime Model

## Build/runtime handoff

Fastboot is a build-time split plus an early runtime loader.

At build time:

- `ts/build/tmp-tree` becomes the early initrd/root filesystem.
- `ts/build/fastboot-tmp` holds deferred payload.
- `fastboot/fastboot-mangle` applies policy lists such as `bin-boot`, `lib-boot`, `etc-ro`, `lib-rw`, and `usr-rw`.
- The deferred payload is packed as `lib.squash`.
- Early-boot executables and every recursive library dependency they need must remain reachable before `lib.squash` is mounted.

Do not diagnose fastboot only from the final root tree. Inspect both the initrd side and the deferred `lib.squash` side.

## Early networking policy

Networking is a boot dependency when `ts-init` or another early consumer may need to retrieve configuration before the normal runtime is fully assembled. In that case, the networking implementation and its dependencies must be available in the early filesystem.

Prefer one networking stack at runtime:

- If the selected image uses NetworkManager and early configuration requires networking, retain NetworkManager, `nm-online`, required libraries, and the early configuration path before deferred payload mounting.
- Make that retention package-aware rather than globally hard-coding NetworkManager into every fastboot image.
- Do not keep NetworkManager and `autonet` active merely as mutual fallbacks; two live networking stacks create ordering and reconfiguration ambiguity.
- Use `autonet` only for an explicit boot path that genuinely requires it.
- Bootstrap networking must still allow later configuration files to change the effective configuration. Reload or regenerate connections after those files are applied.

Validate both initial network acquisition and a later reconfiguration case. A DHCP lease alone does not prove the network lifecycle is correct.

## Package-aware fastboot policy

Early-boot retention should follow selected packages whenever possible.

- Global `bin-boot` and `lib-boot` entries should represent true repository-wide requirements.
- Package-specific early requirements belong with the package's fastboot policy.
- Compare what is selected, what must execute before `lib.squash` exists, what must remain in the early tree, and what may stay deferred.
- Dependency/audit tooling is valuable for proving those relationships even when a broader refactor is not pursued.

## Service ordering

Runtime entrypoint:

```text
/etc/init.d/fastboot
```

Systemd wrapper:

```text
/etc/systemd/system/fastboot.service
```

The service is a oneshot with `RemainAfterExit=yes`, reads `/etc/thinstation.env`, waits for `network-online.target`, and runs before `tsinit.target` and the display manager. Several later services explicitly order after `fastboot.service`, including persistence, session setup, containerd, firewalld, and QEMU guest agent overrides.

If fastboot fails, downstream startup can appear broken even when those downstream packages are correct.

## Loader selection and LM

When `FASTBOOT` is not disabled, the runtime script derives the deferred payload location and chooses a loader from `boot_device`:

- CD/ISO-like boot devices -> ISO loader and `LM=iso`
- hard-disk boot devices -> disk loader and `LM=hd`
- TFTP/HTTP boot devices -> network loader and `LM=pxe`

The loader method is appended to `/etc/thinstation.runtime`. `/etc/profile` uses `LM` to print loader-specific diagnostics if the fastboot service is not active.

## squash_loc and payload naming

`squash_loc()` derives the deferred payload directory from the kernel command line `BOOT_IMAGE` and the inferred initrd path.

Disk boot also derives a kernel-specific squash filename:

```text
vmlinuz[-suffix] -> lib.squash[-suffix]
```

This supports parallel kernel/image variants. Disk mode also recognizes `lib.update`; if present, it replaces the active squash payload before mounting.

## Disk loader

The disk path:

1. determines the boot volume label, preferring `THINSTATION`, then `BOOT`, then `boot`
2. mounts it at `/boot`
3. waits briefly for `lib.squash` or `lib.update`
4. handles the common `/boot/boot/` fallback through `search()`
5. promotes `lib.update` to the active squash when present

For disk failures, verify the filesystem module, the volume label, the `/boot` mount, the derived squash path, and the kernel suffix before changing unrelated packages.

## ISO loader

The ISO path waits for the configured CD volume label, mounts it at `$BASE_MOUNT_PATH/cdrom0`, and locates `lib.squash` either below `boot/` or below the path derived by `squash_loc()`.

For ISO failures, verify:

- `isofs` or `udf` is available
- the CD volume device appeared
- `cdrom0` actually mounted
- `lib.squash` is at the expected relative path

## PXE / HTTP loader

Network boot is treated as memory constrained and downloads the squash payload to:

```text
/tmp/lib.squash
```

Behavior:

- If `FASTBOOT_URL` is set, use HTTP/HTTPS via `wget`.
- If the initrd itself was loaded over HTTP and `FASTBOOT_URL` is empty, infer the base URL from the initrd URL.
- Otherwise wait briefly for `SERVER_IP` and fetch with TFTP using `TFTP_BLOCKSIZE`.

Historically this path favored `autonet`. Treat that as a boot-path constraint, not as a reason to run a second networking stack on ordinary NetworkManager images.

## Mount/decompression modes

`FASTBOOT=lotsofmem`:

- unsquash directly into `/`
- remove a downloaded temporary squash afterward
- no persistent squash mount is required for the deferred payload

Other enabled fastboot mode:

- if memory constrained, mount the squash directly read-only on `/lib64`
- otherwise copy it to `/tmp/lib.squash` first, then mount that copy read-only on `/lib64`

This distinction matters when debugging missing files. In `lotsofmem` mode, inspect the expanded root. In mounted mode, verify the `/lib64` mount and the squash source.

Any fastboot policy change that affects retained files should be validated in both modes. They share source lists but exercise different runtime behavior.

## Failure diagnostics

`/etc/profile` is the operator-facing fallback when the console starts but no graphical/console session was launched.

If fastboot is enabled and `fastboot.service` is not active, it points to:

```text
/var/log/fastboot.log
```

When `DEBUG_BOOT` is set, the fastboot init script enables shell tracing and redirects stdout/stderr there.

The profile then checks loader-specific conditions:

- `LM=hd`: vfat/module availability and `/boot` mount
- `LM=pxe`: early networking/server acquisition
- `LM=iso`: ISO/UDF modules and CD mount
- unknown LM: loader selection never completed correctly

Useful first checks:

```bash
systemctl status fastboot
cat /etc/thinstation.runtime
cat /proc/cmdline
mountpoint /lib64
mountpoint /boot
mountpoint "$BASE_MOUNT_PATH/cdrom0"
tail -200 /var/log/fastboot.log
```

Do not start by debugging Xorg, Docker, firewalld, or persistence if fastboot failed; those components can simply be downstream victims of an incomplete composite filesystem.
