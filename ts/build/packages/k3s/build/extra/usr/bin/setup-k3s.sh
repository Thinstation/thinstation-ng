#!/usr/bin/env bash
set -Eeuo pipefail

PROG=${0##*/}
NON_INTERACTIVE=0; ASSUME_YES=0; REBOOT=1; FORCE_REPARTITION=0
NET_HOSTNAME=${NET_HOSTNAME:-}; NET_IP_ADDRESS=${NET_IP_ADDRESS:-}; NET_CIDR=${NET_CIDR:-}
NET_GATEWAY=${NET_GATEWAY:-}; NET_DNS1=${NET_DNS1:-}; NET_DNS2=${NET_DNS2:-}; NET_DNS_SEARCH=${NET_DNS_SEARCH:-}
A_USER=${A_USER:-admin}; DISK=${DISK:-}; ROOT_PASSWORD_HASH=${ROOT_PASSWORD_HASH:-}; ADMIN_PASSWORD_HASH=${ADMIN_PASSWORD_HASH:-}
log(){ echo "[$PROG] $*"; }; die(){ echo "ERROR: $*" >&2; exit 1; }
usage(){ cat <<USAGE
Usage: setup-k3s.sh [--non-interactive --yes] [--no-reboot] [--repartition]
       [--hostname FQDN] [--ip ADDRESS] [--cidr PREFIX] [--gateway ADDRESS]
       [--dns1 ADDRESS] [--dns2 ADDRESS] [--search-domain DOMAIN]
       [--admin-user USER] [--disk DEVICE]
       [--root-password-hash HASH] [--admin-password-hash HASH]
USAGE
}
while [[ $# -gt 0 ]]; do
 case "$1" in
  --non-interactive) NON_INTERACTIVE=1;; --yes) ASSUME_YES=1;; --no-reboot) REBOOT=0;; --repartition) FORCE_REPARTITION=1;;
  --hostname) NET_HOSTNAME=$2; shift;; --ip) NET_IP_ADDRESS=$2; shift;; --cidr) NET_CIDR=$2; shift;;
  --gateway) NET_GATEWAY=$2; shift;; --dns1) NET_DNS1=$2; shift;; --dns2) NET_DNS2=$2; shift;;
  --search-domain) NET_DNS_SEARCH=$2; shift;; --admin-user) A_USER=$2; shift;; --disk) DISK=$2; shift;;
  --root-password-hash) ROOT_PASSWORD_HASH=$2; shift;; --admin-password-hash) ADMIN_PASSWORD_HASH=$2; shift;;
  -h|--help) usage; exit 0;; *) die "Unknown option: $1";; esac; shift
done
[[ $EUID -eq 0 ]] || die "Run as root"
for c in lsblk wipefs parted pvcreate vgcreate lvcreate mkfs.ext4 nmcli pvs; do command -v "$c" >/dev/null || die "$c required"; done
IFACE=$(ip -4 route show default | awk 'NR==1{print $5}'); [[ -n $IFACE ]] || die "No primary interface"
CURRENT_CIDR=$(ip -4 -o addr show dev "$IFACE" scope global | awk 'NR==1{print $4}')
CURRENT_IP=${CURRENT_CIDR%/*}; CURRENT_PREFIX=${CURRENT_CIDR#*/}; CURRENT_GATEWAY=$(ip -4 route show default | awk 'NR==1{print $3}')
read -r CURRENT_DNS1 CURRENT_DNS2 _ <<<"$(resolvectl dns "$IFACE" 2>/dev/null | awk -F: 'NR==1{gsub(/^ +| +$/,"",$2); print $2}')"
CURRENT_SEARCH=$(resolvectl domain "$IFACE" 2>/dev/null | awk -F: 'NR==1{gsub(/^ +| +$/,"",$2); print $2}' | awk '{print $1}'); [[ $CURRENT_SEARCH == "~." ]] && CURRENT_SEARCH=
NET_HOSTNAME=${NET_HOSTNAME:-$(hostname -f 2>/dev/null || hostname)}; NET_IP_ADDRESS=${NET_IP_ADDRESS:-$CURRENT_IP}; NET_CIDR=${NET_CIDR:-$CURRENT_PREFIX}
NET_GATEWAY=${NET_GATEWAY:-$CURRENT_GATEWAY}; NET_DNS1=${NET_DNS1:-${CURRENT_DNS1:-$CURRENT_GATEWAY}}; NET_DNS2=${NET_DNS2:-${CURRENT_DNS2:-}}; NET_DNS_SEARCH=${NET_DNS_SEARCH:-$CURRENT_SEARCH}
if (( ! NON_INTERACTIVE )); then
 read -rp "Hostname [$NET_HOSTNAME]: " v; NET_HOSTNAME=${v:-$NET_HOSTNAME}; read -rp "IPv4 [$NET_IP_ADDRESS]: " v; NET_IP_ADDRESS=${v:-$NET_IP_ADDRESS}
 read -rp "CIDR [$NET_CIDR]: " v; NET_CIDR=${v:-$NET_CIDR}; read -rp "Gateway [$NET_GATEWAY]: " v; NET_GATEWAY=${v:-$NET_GATEWAY}
 read -rp "DNS [$NET_DNS1]: " v; NET_DNS1=${v:-$NET_DNS1}; read -rp "Search [${NET_DNS_SEARCH:-none}]: " v; NET_DNS_SEARCH=${v:-$NET_DNS_SEARCH}
 read -rp "Admin user [$A_USER]: " v; A_USER=${v:-$A_USER}
fi
VG=ts_persistent; EXPECTED=(prstnt log k3s-data); READY=1; for lv in "${EXPECTED[@]}"; do [[ -b /dev/$VG/$lv ]] || READY=0; done
if (( READY && ! FORCE_REPARTITION )); then REUSE=1; DISK=${DISK:-$(pvs --noheadings -o pv_name,vg_name | awk -v vg="$VG" '$2==vg{print $1; exit}' | sed -E "s/p?[0-9]+$//")};
else REUSE=0; if [[ -z $DISK ]]; then mapfile -t D < <(lsblk -dn -o NAME,TYPE | awk '$2=="disk"{print "/dev/"$1}'); [[ ${#D[@]} -eq 1 ]] && DISK=${D[0]} || { (( NON_INTERACTIVE )) && die "Specify --disk"; select x in "${D[@]}"; do [[ -n ${x:-} ]] && { DISK=$x; break; }; done; }; fi; fi
cat <<SUMMARY
K3s appliance setup
  Hostname: $NET_HOSTNAME
  Address:  $NET_IP_ADDRESS/$NET_CIDR
  Gateway:  $NET_GATEWAY
  Storage:  $([[ $REUSE -eq 1 ]] && echo "reuse $VG" || echo "initialize $DISK")
SUMMARY
if (( NON_INTERACTIVE )); then (( ASSUME_YES )) || die "--non-interactive requires --yes"; elif (( ! ASSUME_YES )); then read -rp "Type YES to apply: " yes; [[ $yes == YES ]] || die Aborted; fi
systemctl stop k3s persistent-files persistent-dirs 2>/dev/null || true
if (( ! REUSE )); then
 [[ -b $DISK ]] || die "Disk not found: $DISK"; while read -r mp; do [[ -n $mp ]] && umount -lf "$mp" || true; done < <(lsblk -nr -o MOUNTPOINT "$DISK" | awk NF)
 wipefs -a "$DISK"; sgdisk --zap-all "$DISK" 2>/dev/null || true; parted -s "$DISK" mklabel gpt; parted -s "$DISK" mkpart primary 1MiB 100%; parted -s "$DISK" set 1 lvm on; partprobe "$DISK"; udevadm settle
 PART=${DISK}1; [[ -b $PART ]] || PART=${DISK}p1; [[ -b $PART ]] || die "Partition not found"
 pvcreate -ff -y "$PART"; vgcreate "$VG" "$PART"; lvcreate -y -L 1G -n prstnt "$VG"; lvcreate -y -L 4G -n log "$VG"; lvcreate -y -l 100%FREE -n k3s-data "$VG"
 mkfs.ext4 -F -L prstnt /dev/$VG/prstnt; mkfs.ext4 -F -L log /dev/$VG/log; mkfs.ext4 -F -L k3s-data /dev/$VG/k3s-data
fi
/usr/bin/k3s-storage-mount
for mp in /var/prstnt /var/log /var/lib/rancher/k3s; do mountpoint -q "$mp" || die "Persistent mount failed: $mp"; done
touch /var/lib/rancher/k3s/.configured
if id "$A_USER" >/dev/null 2>&1; then :; elif id tsuser >/dev/null 2>&1; then groupmod -n "$A_USER" tsuser; usermod -l "$A_USER" -m -d "/home/$A_USER" tsuser; else useradd -m -s /bin/sh "$A_USER"; fi
[[ -z $ADMIN_PASSWORD_HASH ]] || usermod -p "$ADMIN_PASSWORD_HASH" "$A_USER"; [[ -z $ROOT_PASSWORD_HASH ]] || usermod -p "$ROOT_PASSWORD_HASH" root
install -d -m 0750 /etc/sudoers.d; printf "%s ALL=(ALL) NOPASSWD: ALL\n" "$A_USER" >/etc/sudoers.d/$A_USER; chmod 0440 /etc/sudoers.d/$A_USER
CON=D1; DNS=$NET_DNS1${NET_DNS2:+,$NET_DNS2}; CIDR=$NET_IP_ADDRESS/$NET_CIDR
if nmcli -t -f NAME con show | grep -Fxq "$CON"; then nmcli con modify "$CON" connection.interface-name "$IFACE" ipv4.method manual ipv4.addresses "$CIDR" ipv4.gateway "$NET_GATEWAY" ipv4.dns "$DNS" ipv4.dns-search "$NET_DNS_SEARCH" ipv6.method disabled connection.autoconnect yes; else nmcli con add con-name "$CON" type ethernet ifname "$IFACE" ipv4.method manual ipv4.addresses "$CIDR" ipv4.gateway "$NET_GATEWAY" ipv4.dns "$DNS" ipv4.dns-search "$NET_DNS_SEARCH" ipv6.method disabled autoconnect yes; fi
nmcli con up "$CON"; hostnamectl set-hostname "$NET_HOSTNAME"
cat >/etc/thinstation.custom <<CUSTOM
NET_HOSTNAME=$NET_HOSTNAME
NET_USE_DHCP=Off
CUSTOM
mkdir -p /var/lib/rancher/k3s/server/manifests; SEED=/usr/lib64/thinstation/k3s-manifests; [[ ! -d $SEED ]] || cp -a "$SEED"/. /var/lib/rancher/k3s/server/manifests/
/usr/bin/k3s-image-sync || true; systemctl start k3s
log "Waiting for Kubernetes API"; ok=0; for _ in $(seq 1 60); do /usr/bin/k3s kubectl get --raw=/readyz >/dev/null 2>&1 && { ok=1; break; }; sleep 2; done; (( ok )) || { systemctl --no-pager --full status k3s || true; die "K3s API not ready"; }
/usr/bin/k3s kubectl get nodes -o wide
/etc/init.d/persistent-files backup; /etc/init.d/persistent-dirs backup; systemctl start persistent-dirs persistent-files
log "K3s appliance setup complete"; (( REBOOT )) && reboot || true
