---
name: thinstation-boot-validation
description: Test and debug ThinStation boot/runtime behavior. Use for ts/bin/bt, QEMU, BIOS/UEFI/Secure Boot, OVMF, PXE/iPXE, fastboot/lib.squash, QEMU Guest Agent automation, SSH debug paths, persistent raw disks, graceful reboot tests, and diagnosing whether a built ISO reached userspace.
---

# ThinStation Boot Validation

Prefer direct runtime evidence over guessing from source.

## Test order

1. Use the smallest `bt` mode that proves the change.
2. Confirm the QEMU process and QGA socket.
3. Use QGA for guest status/commands before depending on SSH.
4. For persistent appliances, fresh disk -> setup -> healthy -> graceful stop -> same disk -> healthy.
5. Repeat EFI for appliance images intended for Proxmox/modern VM deployment.
6. Use Secure Boot/PXE variants when the changed area touches those paths.

## References

- `references/boot-and-test-architecture.md` — bt matrix, OVMF, PXE, persistent disks, QGA protocol details.
- `references/fastboot-runtime.md` — initrd/lib.squash split and runtime loader diagnostics.
- `references/lab-validation.md` — guest inspection and live-service troubleshooting.
