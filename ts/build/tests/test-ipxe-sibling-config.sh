#!/bin/bash
set -Eeuo pipefail

work="${CI_PROJECT_DIR:-$PWD}/ipxe-sibling-test"
rm -rf "$work"
mkdir -p "$work/tftp/nested" "$work/src" "$work/f45"

cat > "$work/bios-bootstrap.ipxe" <<'EOF'
#!ipxe
chain autoexec.ipxe || exit 1
EOF

cat > "$work/tftp/nested/autoexec.ipxe" <<'EOF'
#!ipxe
chain thinstation.ipxe || exit 1
EOF

cat > "$work/tftp/nested/thinstation.ipxe" <<'EOF'
#!ipxe
echo TSIPXE_BIOS_SIBLING_OK
exit
EOF

git clone --depth 1 --branch v2.0.0 https://github.com/ipxe/ipxe.git "$work/src/ipxe"
make -C "$work/src/ipxe/src" -j"$(nproc)" NO_WERROR=1 \
  bin/undionly.kpxe EMBED="$work/bios-bootstrap.ipxe"
cp "$work/src/ipxe/src/bin/undionly.kpxe" "$work/tftp/nested/undionly.kpxe"

dnf download --destdir "$work/f45" --releasever=45 --repo=fedora ipxe-bootimgs-x86
rpm2cpio "$work"/f45/ipxe-bootimgs-x86-*.rpm | (cd "$work/f45" && cpio -idm --quiet)
uefi_image="$(find "$work/f45" -type f \
  \( -name 'ipxe-snponly-x86_64.efi' -o -name 'ipxe-x86_64.efi' \) | head -1)"
test -n "$uefi_image"

timeout 30 qemu-system-x86_64 \
  -accel kvm -machine q35 -m 512 -smp 1 -boot n \
  -device e1000,netdev=n1 \
  -netdev user,id=n1,tftp="$work/tftp",bootfile=/nested/undionly.kpxe \
  -object filter-dump,id=dump1,netdev=n1,file="$work/bios.pcap" \
  -display none -monitor none -serial stdio -no-reboot \
  >"$work/bios.log" 2>&1 || true

tcpdump -nn -vvv -r "$work/bios.pcap" > "$work/bios.packets" 2>&1 || true
strings "$work/bios.pcap" > "$work/bios.strings"

grep -q 'nested/autoexec.ipxe' "$work/bios.strings" || {
  echo "BIOS did not request sibling nested/autoexec.ipxe" >&2
  exit 1
}
grep -q 'nested/thinstation.ipxe' "$work/bios.strings" || {
  echo "BIOS autoexec did not request sibling nested/thinstation.ipxe" >&2
  exit 1
}
echo "BIOS sibling chaining: PASS"

ovmf_code="$(find /usr/share/edk2 /usr/share/OVMF -type f -name 'OVMF_CODE.fd' 2>/dev/null | head -1)"
test -n "$ovmf_code"

mkdir -p "$work/esp/EFI/BOOT"
cp "$uefi_image" "$work/esp/EFI/BOOT/BOOTX64.EFI"

cat > "$work/esp/EFI/BOOT/autoexec.ipxe" <<'EOF'
#!ipxe
chain thinstation.ipxe || exit 1
EOF

cat > "$work/esp/EFI/BOOT/thinstation.ipxe" <<'EOF'
#!ipxe
echo TSIPXE_UEFI_SIBLING_OK
exit
EOF

timeout 15 qemu-system-x86_64 \
  -accel kvm -machine q35 -m 512 -smp 1 \
  -drive if=pflash,format=raw,readonly=on,file="$ovmf_code" \
  -drive format=raw,file=fat:rw:"$work/esp" \
  -display none -monitor none -serial stdio -no-reboot \
  >"$work/uefi.log" 2>&1 || true

grep -q 'file:autoexec.ipxe.*ok' "$work/uefi.log" || {
  echo "UEFI did not load autoexec.ipxe beside BOOTX64.EFI" >&2
  exit 1
}
grep -q 'thinstation.ipxe.*ok' "$work/uefi.log" || {
  echo "UEFI autoexec did not resolve sibling thinstation.ipxe" >&2
  exit 1
}
echo "UEFI sibling chaining: PASS"
