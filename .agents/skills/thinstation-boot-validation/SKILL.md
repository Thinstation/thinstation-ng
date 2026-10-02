---
name: thinstation-boot-validation
description: Test and qualify ThinStation images locally with repository-native tooling. Use for ts/bin/bt, QEMU, BIOS/UEFI/Secure Boot, OVMF, PXE/iPXE, fastboot/lib.squash, QEMU Guest Agent automation, local SSH debug paths, persistent raw disks, graceful reboot tests, and proving that a build satisfies a target definition before commit.
---

# ThinStation Boot Validation

Prefer local, reproducible evidence over environment-specific deployment testing.

## Qualification workflow

1. Start from the target definition's required boot modes and runtime behavior.
2. Use the smallest relevant `bt` mode first.
3. Confirm QEMU process state and QGA before depending on SSH.
4. Verify expected filesystem/package/service state inside the guest.
5. For persistent targets: fresh disk -> configure -> healthy -> graceful stop -> same disk -> healthy.
6. Validate EFI when the target requires modern virtual/physical deployment; validate Secure Boot/PXE only when required.
7. Record failures as repository-level causes and fix the source/configuration rather than adapting to a private deployment environment.
8. Stop all test VMs and leave qualification artifacts outside the committed source diff.

## References

- `references/boot-and-test-architecture.md` — bt matrix, OVMF, PXE, persistent disks, QGA protocol details.
- `references/fastboot-runtime.md` — initrd/lib.squash split and runtime loader diagnostics.
- `references/local-qemu-validation.md` — local guest inspection and qualification checklist.
