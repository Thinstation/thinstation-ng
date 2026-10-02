# Boot and Test Architecture

## Fast iteration hierarchy

Prefer the cheapest local test that proves the hypothesis.

1. Run a focused parser/build/tool command.
2. Reuse an initialized chroot and existing generated artifacts when safe.
3. Rebuild only the affected boot/image output when required.
4. Run the repository CI pipeline only for integration/final validation or when pipeline behavior itself is under test.

When using `setup-chroot`, initialize the full environment before applying a minimal active profile. A stale partial chroot can look initialized while required tools are missing; repair the chroot state rather than resetting source.

Inside the chroot, `/build` maps to `ts/build`. Write diagnostic artifacts that must survive chroot exit under `/build`, not transient chroot `/tmp`.

## Network boot output contract

The generated tree:

`ts/build/boot-images/grub/efi-source`

is the hostable network-boot root. Serve the same tree directly over TFTP and HTTP. Do not create a second staged copy merely for testing.

Boot files:

- BIOS: `/boot/ipxe/undionly.kpxe`
- UEFI: `/boot/ipxe/snponly.efi`
- UEFI Secure Boot: `/boot/ipxe/snponly-shim.efi`
- Universal script: `/boot/ipxe/autoexec.ipxe`

The shipped `autoexec.ipxe` must work unchanged for BIOS, ordinary UEFI, and Secure Boot UEFI. Its essential flow is:

```ipxe
set boot_url http://${next-server}
set BOOT_IMAGE /boot/vmlinuz
kernel ${boot_url}${BOOT_IMAGE} BOOT_IMAGE=${BOOT_IMAGE} ... boot_device=${boot_url}
initrd ${boot_url}/boot/initrd
iseq ${platform} efi && shim ${boot_url}/EFI/BOOT/BOOTX64.EFI ||
boot
```

BIOS skips the shim command. UEFI loads Fedora's signed shim. This also works when Secure Boot is disabled, so one script is sufficient for all three modes.

## Secure Boot chain

The working network chain is:

`UEFI firmware -> iPXE secure shim -> signed iPXE -> Fedora shim -> Fedora-signed kernel -> ThinStation initrd`

Important consequences:

- ThinStation uses a Fedora-signed kernel, so no ThinStation kernel-signing key is required for this path.
- The custom ThinStation initrd is ordinary data consumed by the trusted kernel and does not need the Fedora shim private key.
- Fedora's `EFI/BOOT/BOOTX64.EFI` supplies the Fedora Secure Boot CA used to validate the Fedora kernel.
- The iPXE secure loader pair under `/boot/ipxe` is distinct from Fedora's shim used later by iPXE's `shim` command.

For QEMU Secure Boot tests, use `OVMF_CODE.secboot.fd` plus a writable copy of `OVMF_VARS.secboot.fd`. Never modify the packaged VARS template in place.

## Modern OVMF PXE requirement

Modern edk2 NetworkPkg requires `EFI_RNG_PROTOCOL` for DHCP/PXE after the CVE-2023-45237 hardening. A QEMU network-boot test without an RNG device can misleadingly fail with:

`BdsDxe: No bootable option or device was found.`

Provide:

```text
-object rng-random,filename=/dev/urandom,id=RNG
-device virtio-rng-pci,rng=RNG
```

Fedora OVMF's built-in virtio network driver is sufficient once RNG is present. Do not add an external `efi-virtio.rom` workaround unless a separate test proves it is required.

This behavior was isolated by comparing edk2 revisions: 2023-era firmware PXE-booted without RNG, while firmware containing the CVE-2023-45237 DHCP hardening required an EFI RNG source.

## `bt` boot-test matrix

Maintain these working modes:

| Firmware | HD | CD | NET |
| --- | --- | --- | --- |
| BIOS | `hd` | `cd` | `net` |
| UEFI | `hd-efi` | `cd-efi` | `net-efi` |
| UEFI Secure Boot | `hd-efi-secure` | `cd-efi-secure` | `net-efi-secure` |

DevStation's Test-Build menu should expose the same nine modes.

Network modes should serve `/build/boot-images/grub/efi-source` directly. The test HTTP server should use that directory as its document root; TFTP should use the same root.

## QEMU diagnostic hooks

For headless or automated tests, prefer direct evidence over GUI inspection:

- `BT_SERIAL_FILE=/build/<name>.serial` for persistent firmware/guest serial capture.
- `BT_PCAP_FILE=/build/<name>.pcap` for packet-level proof of requested boot files.
- `BT_SERIAL_WAIT=on` only when an interactive serial client must attach before firmware starts.
- `--remote` for headless runner execution.

A pcap is often more decisive than console output. Verify the actual sequence: loader request, sibling `autoexec.ipxe`, HTTP `vmlinuz`, HTTP `initrd`, Fedora shim for UEFI, and later `lib.squash` when applicable.

## Checkout ownership

Run Git operations as the checkout owner rather than adding broad `safe.directory` exceptions or changing ownership on initialized build trees.

## Persistent data-disk testing

Use `mkgptdrv --data-only` to create disposable GPT storage images without a fake boot partition or overlay:

```bash
sudo env AGREE=true ts/bin/mkgptdrv --data-only \
  -l ts/build/bt-vms/k3s-test.img:10G \
  -p l:1G:prstnt \
  -p l:1G:log \
  -p l:0:k3s-data
```

Data-only mode requires explicit partitions and an explicit loopfile size. Formatting failures must still detach loop devices. Keep large test images off small tmpfs or `/tmp` filesystems.

Use `bt --disk-image PATH` to attach existing raw virtio disks. The option is repeatable. For persistence tests, use `cache=none`; in CD/EFI modes explicit disks replace the implicit global `/usbhd.img`.

For stateful-appliance validation:

1. Create a fresh data disk.
2. Boot ISO + data disk.
3. Wait for Ready.
4. Gracefully power off through ACPI/systemd.
5. Wait for QEMU to release the image.
6. Boot the exact same disk.
7. Verify database, certificates, node identity, mounts, and service readiness.

Do not diagnose persistence from a hard QEMU kill with writeback caching; it can mimic corrupted or partially flushed application state.

## Active profile handoff

Editing `ts/build/conf/<profile>/build.conf.example` does not change an already active `ts/build/build.conf`. Before validating profile changes, copy/sync the profile into the active build tree. For kernel command-line changes, verify the generated GRUB/iPXE configuration before booting.


## QGA automation details

For repeated automated guest commands, prefer a persistent UNIX-socket client and attach an `id` to every QGA request. Match responses by request ID and ignore stale queued responses. One-shot socket clients can leave prior replies queued and make later reads appear one message behind.

A reliable sequence is:

1. connect to the VM's `qga.sock`,
2. send `guest-ping` with an ID,
3. start work with `guest-exec`,
4. retain the returned guest PID,
5. poll `guest-exec-status` by PID until `exited=true`.

Do not assume losing SSH means the guest is dead; first-run network reconfiguration can intentionally replace the active NetworkManager profile while QGA remains available.

## bt process/state cleanup

Distinguish live QEMU processes from stale `bt` metadata.

- Kill exact QEMU PIDs or holders of a specific disk image rather than broad pattern matches.
- A stopped VM directory can still confuse automatic serial/monitor port allocation.
- When validating a single test, explicit unused serial/monitor/SSH ports are acceptable.
- Before reusing a raw disk, confirm no process holds a write lock on it.
