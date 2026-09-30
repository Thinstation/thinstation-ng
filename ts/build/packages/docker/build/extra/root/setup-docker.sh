#!/usr/bin/env bash
set -Eeuo pipefail

PROG="${0##*/}"
NON_INTERACTIVE=0
ASSUME_YES=0
REBOOT=1
FORCE_REPARTITION=0
REUSE_STORAGE=1

NET_HOSTNAME="${NET_HOSTNAME:-}"
NET_IP_ADDRESS="${NET_IP_ADDRESS:-}"
NET_CIDR="${NET_CIDR:-}"
NET_GATEWAY="${NET_GATEWAY:-}"
NET_DNS1="${NET_DNS1:-}"
NET_DNS2="${NET_DNS2:-}"
NET_DNS_SEARCH="${NET_DNS_SEARCH:-}"
A_USER="${A_USER:-}"
DISK="${DISK:-}"
ROOT_PASSWORD_HASH="${ROOT_PASSWORD_HASH:-}"
ADMIN_PASSWORD_HASH="${ADMIN_PASSWORD_HASH:-}"

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[$PROG] $*"; }

usage() {
  cat <<'EOF'
Usage: setup-docker.sh [options]

Interactive mode derives defaults from the running system, shows a summary,
and requires approval before making changes.

Options:
  --non-interactive       Never prompt. Requires --yes to apply.
  --yes                   Approve the proposed configuration.
  --no-reboot             Do not reboot when setup completes.
  --repartition           Destroy/recreate persistent storage even if it exists.
  --hostname FQDN         Static hostname.
  --ip ADDRESS            Static IPv4 address.
  --cidr PREFIX           IPv4 CIDR prefix.
  --gateway ADDRESS       IPv4 gateway.
  --dns1 ADDRESS          Primary DNS server.
  --dns2 ADDRESS          Secondary DNS server (optional).
  --search-domain DOMAIN  DNS search domain.
  --admin-user USER       Administrative user name.
  --disk DEVICE           Persistent storage disk, e.g. /dev/sda.
  --root-password-hash H  crypt(3) password hash for root.
  --admin-password-hash H crypt(3) password hash for the admin user.
  -h, --help              Show this help.

The same values may be supplied by environment variables:
NET_HOSTNAME, NET_IP_ADDRESS, NET_CIDR, NET_GATEWAY, NET_DNS1, NET_DNS2,
NET_DNS_SEARCH, A_USER, DISK, ROOT_PASSWORD_HASH, ADMIN_PASSWORD_HASH.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive) NON_INTERACTIVE=1 ;;
    --yes) ASSUME_YES=1 ;;
    --no-reboot) REBOOT=0 ;;
    --repartition) FORCE_REPARTITION=1; REUSE_STORAGE=0 ;;
    --hostname) NET_HOSTNAME="$2"; shift ;;
    --ip) NET_IP_ADDRESS="$2"; shift ;;
    --cidr) NET_CIDR="$2"; shift ;;
    --gateway) NET_GATEWAY="$2"; shift ;;
    --dns1) NET_DNS1="$2"; shift ;;
    --dns2) NET_DNS2="$2"; shift ;;
    --search-domain) NET_DNS_SEARCH="$2"; shift ;;
    --admin-user) A_USER="$2"; shift ;;
    --disk) DISK="$2"; shift ;;
    --root-password-hash) ROOT_PASSWORD_HASH="$2"; shift ;;
    --admin-password-hash) ADMIN_PASSWORD_HASH="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "Run as root."

for cmd in lsblk wipefs parted pvcreate vgcreate lvcreate mkfs.ext4 nmcli findmnt usermod groupmod; do
  command -v "$cmd" >/dev/null || die "$cmd required."
done

valid_user() {
  [[ "$1" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]
}
valid_ipv4() {
  local ip="$1" a b c d octet
  [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS=. read -r a b c d <<<"$ip"
  for octet in "$a" "$b" "$c" "$d"; do
    (( octet >= 0 && octet <= 255 )) || return 1
  done
}
valid_cidr() {
  [[ "$1" =~ ^[0-9]{1,2}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 32 ))
}
valid_fqdn() {
  [[ ${#1} -le 253 && "$1" == *.* &&
     "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]]
}

default_iface() {
  ip -4 route show default 2>/dev/null | awk 'NR==1{print $5}'
}
default_ip_cidr() {
  local iface="$1"
  ip -4 -o addr show dev "$iface" scope global 2>/dev/null | awk 'NR==1{print $4}'
}
default_gateway() {
  ip -4 route show default 2>/dev/null | awk 'NR==1{print $3}'
}
default_dns() {
  local iface="$1"
  resolvectl dns "$iface" 2>/dev/null | awk -F: 'NR==1{gsub(/^ +| +$/,"",$2); print $2}'
}
default_search() {
  local iface="$1"
  local s
  s="$(resolvectl domain "$iface" 2>/dev/null | awk -F: 'NR==1{gsub(/^ +| +$/,"",$2); print $2}' | awk '{print $1}')"
  [[ "$s" == "~." ]] && s=""
  [[ -n "$s" ]] || s="$(awk '/^search /{print $2; exit}' /etc/resolv.conf 2>/dev/null || true)"
  printf '%s\n' "$s"
}

prompt_value() {
  local var="$1" label="$2" validator="$3" def="$4" value=""
  while true; do
    read -rp "$label [${def}]: " value
    value="${value:-$def}"
    if "$validator" "$value"; then
      printf -v "$var" '%s' "$value"
      return
    fi
    echo "Invalid value: $value"
  done
}

prompt_optional_ip() {
  local var="$1" label="$2" def="$3" value=""
  while true; do
    read -rp "$label [${def:-none}]: " value
    value="${value:-$def}"
    if [[ -z "$value" ]] || valid_ipv4 "$value"; then
      printf -v "$var" '%s' "$value"
      return
    fi
    echo "Invalid IPv4 address: $value"
  done
}

IFACE="$(default_iface)"
[[ -n "$IFACE" ]] || die "Unable to determine primary network interface."

CURRENT_CIDR="$(default_ip_cidr "$IFACE")"
CURRENT_IP="${CURRENT_CIDR%/*}"
CURRENT_PREFIX="${CURRENT_CIDR#*/}"
CURRENT_GATEWAY="$(default_gateway)"
read -r CURRENT_DNS1 CURRENT_DNS2 _ <<<"$(default_dns "$IFACE")"
CURRENT_SEARCH="$(default_search "$IFACE")"
CURRENT_HOSTNAME="$(hostname -f 2>/dev/null || hostname)"
if [[ "$CURRENT_HOSTNAME" != *.* && -n "$CURRENT_SEARCH" ]]; then
  CURRENT_HOSTNAME="${CURRENT_HOSTNAME}.${CURRENT_SEARCH}"
fi

NET_IP_ADDRESS="${NET_IP_ADDRESS:-$CURRENT_IP}"
NET_CIDR="${NET_CIDR:-$CURRENT_PREFIX}"
NET_GATEWAY="${NET_GATEWAY:-$CURRENT_GATEWAY}"
NET_DNS1="${NET_DNS1:-${CURRENT_DNS1:-$CURRENT_GATEWAY}}"
NET_DNS2="${NET_DNS2:-${CURRENT_DNS2:-}}"
NET_DNS_SEARCH="${NET_DNS_SEARCH:-$CURRENT_SEARCH}"
NET_HOSTNAME="${NET_HOSTNAME:-$CURRENT_HOSTNAME}"
A_USER="${A_USER:-admin}"

if (( ! NON_INTERACTIVE )); then
  echo
  echo "ThinStation Docker appliance setup"
  echo "Press Enter to accept each derived default."
  prompt_value NET_HOSTNAME "Hostname (FQDN)" valid_fqdn "$NET_HOSTNAME"
  prompt_value NET_IP_ADDRESS "Static IPv4 address" valid_ipv4 "$NET_IP_ADDRESS"
  prompt_value NET_CIDR "CIDR prefix" valid_cidr "$NET_CIDR"
  prompt_value NET_GATEWAY "IPv4 gateway" valid_ipv4 "$NET_GATEWAY"
  prompt_value NET_DNS1 "Primary DNS server" valid_ipv4 "$NET_DNS1"
  prompt_optional_ip NET_DNS2 "Secondary DNS server" "$NET_DNS2"
  NET_DNS_SEARCH="${NET_DNS_SEARCH:-${NET_HOSTNAME#*.}}"
  read -rp "DNS search domain [${NET_DNS_SEARCH}]: " answer
  NET_DNS_SEARCH="${answer:-$NET_DNS_SEARCH}"
  prompt_value A_USER "Administrative user" valid_user "$A_USER"
fi

valid_fqdn "$NET_HOSTNAME" || die "Invalid hostname: $NET_HOSTNAME"
valid_ipv4 "$NET_IP_ADDRESS" || die "Invalid IPv4 address: $NET_IP_ADDRESS"
valid_cidr "$NET_CIDR" || die "Invalid CIDR: $NET_CIDR"
valid_ipv4 "$NET_GATEWAY" || die "Invalid gateway: $NET_GATEWAY"
valid_ipv4 "$NET_DNS1" || die "Invalid primary DNS: $NET_DNS1"
[[ -z "$NET_DNS2" ]] || valid_ipv4 "$NET_DNS2" || die "Invalid secondary DNS: $NET_DNS2"
valid_user "$A_USER" || die "Invalid admin user: $A_USER"

VG_NAME="ts_persistent"
EXPECTED_LVS=(prstnt docker log docker-data container-data)
storage_ready=1
for lv in "${EXPECTED_LVS[@]}"; do
  [[ -b "/dev/$VG_NAME/$lv" ]] || storage_ready=0
done

if (( storage_ready && ! FORCE_REPARTITION )); then
  REUSE_STORAGE=1
  DISK="${DISK:-$(pvs --noheadings -o pv_name,vg_name 2>/dev/null | awk -v vg="$VG_NAME" '$2==vg{print $1; exit}' | sed -E 's/p?[0-9]+$//')}"
else
  REUSE_STORAGE=0
  if [[ -z "$DISK" ]]; then
    mapfile -t CANDIDATES < <(lsblk -dn -o NAME,TYPE | awk '$2=="disk"{print "/dev/"$1}')
    if [[ ${#CANDIDATES[@]} -eq 1 ]]; then
      DISK="${CANDIDATES[0]}"
    elif (( NON_INTERACTIVE )); then
      die "Multiple disks found; specify --disk."
    else
      echo "Candidate persistent storage disks:"
      select choice in "${CANDIDATES[@]}"; do
        [[ -n "${choice:-}" ]] || continue
        DISK="$choice"
        break
      done
    fi
  fi
fi

echo
echo "Proposed configuration"
printf '  Hostname:       %s\n' "$NET_HOSTNAME"
printf '  Interface:      %s\n' "$IFACE"
printf '  Address:        %s/%s\n' "$NET_IP_ADDRESS" "$NET_CIDR"
printf '  Gateway:        %s\n' "$NET_GATEWAY"
printf '  DNS:            %s%s\n' "$NET_DNS1" "${NET_DNS2:+, $NET_DNS2}"
printf '  Search domain:  %s\n' "$NET_DNS_SEARCH"
printf '  Admin user:     %s\n' "$A_USER"
if (( REUSE_STORAGE )); then
  printf '  Storage:        reuse existing %s volumes\n' "$VG_NAME"
else
  printf '  Storage:        DESTROY and initialize %s\n' "$DISK"
fi
printf '  Reboot:         %s\n' "$([[ $REBOOT -eq 1 ]] && echo yes || echo no)"
echo

if (( NON_INTERACTIVE )); then
  (( ASSUME_YES )) || die "--non-interactive requires --yes."
elif (( ! ASSUME_YES )); then
  read -rp "Apply this configuration? Type YES to continue: " CONFIRM
  [[ "$CONFIRM" == "YES" ]] || die "Aborted."
fi

systemctl stop docker 2>/dev/null || true
systemctl stop containerd 2>/dev/null || true
systemctl stop persistent-files 2>/dev/null || true
systemctl stop persistent-dirs 2>/dev/null || true

if (( ! REUSE_STORAGE )); then
  [[ -b "$DISK" ]] || die "Storage disk not found: $DISK"

  log "Unmounting filesystems on $DISK"
  while read -r mp; do
    [[ -n "$mp" ]] && umount -lf "$mp" || true
  done < <(lsblk -nr -o MOUNTPOINT "$DISK" | awk 'NF')

  mapfile -t OLD_PVS < <(pvs --noheadings -o pv_name 2>/dev/null | awk -v d="$DISK" '$1 ~ "^"d {print $1}')
  for pv in "${OLD_PVS[@]}"; do
    vg="$(pvs --noheadings -o vg_name "$pv" 2>/dev/null | awk 'NF{print $1}')"
    [[ -z "$vg" ]] || { vgchange -an "$vg" || true; vgremove -ff "$vg" || true; }
  done

  log "Creating persistent storage on $DISK"
  wipefs -a "$DISK"
  sgdisk --zap-all "$DISK" 2>/dev/null || true
  parted -s "$DISK" mklabel gpt
  parted -s "$DISK" mkpart primary 1MiB 100%
  parted -s "$DISK" set 1 lvm on
  partprobe "$DISK"
  udevadm settle || true

  PART="${DISK}1"
  [[ -b "$PART" ]] || PART="${DISK}p1"
  [[ -b "$PART" ]] || die "Could not find new partition."

  pvcreate -ff -y "$PART"
  vgcreate "$VG_NAME" "$PART"
  lvcreate -y -L 1G -n prstnt "$VG_NAME"
  lvcreate -y -L 1G -n docker "$VG_NAME"
  lvcreate -y -L 4G -n log "$VG_NAME"
  lvcreate -y -L 2G -n docker-data "$VG_NAME"
  lvcreate -y -l 100%FREE -n container-data "$VG_NAME"

  mkfs.ext4 -F -L prstnt "/dev/$VG_NAME/prstnt"
  mkfs.ext4 -F -L docker "/dev/$VG_NAME/docker"
  mkfs.ext4 -F -L log "/dev/$VG_NAME/log"
  mkfs.ext4 -F -L docker-data "/dev/$VG_NAME/docker-data"
  mkfs.ext4 -F -L container-data "/dev/$VG_NAME/container-data"
fi

mkdir -p /var/prstnt /docker /var/log /var/lib/docker /var/lib/containerd

for mp in /var/prstnt /var/log /docker /var/lib/docker /var/lib/containerd; do
  mountpoint -q "$mp" || mount "$mp"
done

DOCKER_SEED_ROOT="${DOCKER_SEED_ROOT:-/usr/lib/thinstation/docker-stacks}"

log "Applying identity and network configuration"
if id "$A_USER" >/dev/null 2>&1; then
  :
elif id tsuser >/dev/null 2>&1; then
  groupmod -n "$A_USER" tsuser
  usermod -l "$A_USER" -m -d "/home/$A_USER" tsuser
else
  useradd -m -s /bin/sh "$A_USER"
fi

if [[ -n "$ADMIN_PASSWORD_HASH" ]]; then
  usermod -p "$ADMIN_PASSWORD_HASH" "$A_USER"
elif (( ! NON_INTERACTIVE )); then
  echo "Set password for $A_USER"
  passwd "$A_USER"
fi

if [[ -n "$ROOT_PASSWORD_HASH" ]]; then
  usermod -p "$ROOT_PASSWORD_HASH" root
elif (( ! NON_INTERACTIVE )); then
  echo "Set password for root"
  passwd root
fi

install -d -m 0750 /etc/sudoers.d
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$A_USER" >"/etc/sudoers.d/$A_USER"
chmod 0440 "/etc/sudoers.d/$A_USER"

CON_NAME="D1"
IP_CIDR="${NET_IP_ADDRESS}/${NET_CIDR}"
if nmcli -t -f NAME con show | grep -Fxq "$CON_NAME"; then
  nmcli con modify "$CON_NAME"     connection.interface-name "$IFACE"     ipv4.method manual     ipv4.addresses "$IP_CIDR"     ipv4.gateway "$NET_GATEWAY"     ipv4.dns "$NET_DNS1${NET_DNS2:+,$NET_DNS2}"     ipv4.dns-search "$NET_DNS_SEARCH"     connection.autoconnect yes
else
  nmcli con add con-name "$CON_NAME" type ethernet ifname "$IFACE"     ipv4.method manual     ipv4.addresses "$IP_CIDR"     ipv4.gateway "$NET_GATEWAY"     ipv4.dns "$NET_DNS1${NET_DNS2:+,$NET_DNS2}"     ipv4.dns-search "$NET_DNS_SEARCH"     autoconnect yes
fi

for old in $(nmcli -t -f NAME,DEVICE con show | awk -F: -v ifc="$IFACE" '$2==ifc && $1!="D1"{print $1}'); do
  nmcli con delete "$old" >/dev/null 2>&1 || true
done
nmcli con up "$CON_NAME"
hostnamectl set-hostname "$NET_HOSTNAME"

cat >/etc/thinstation.custom <<EOF
NET_HOSTNAME=$NET_HOSTNAME
NET_USE_DHCP=Off
EOF

log "Seeding appliance compose payload"
if [[ -d "$DOCKER_SEED_ROOT" ]]; then
  cp -a "$DOCKER_SEED_ROOT"/. /docker/
fi

log "Starting Docker and loading ISO images"
systemctl start containerd
systemctl start docker
/usr/bin/docker-iso-update

log "Starting compose stacks"
shopt -s nullglob
for stack in /docker/*; do
  [[ -d "$stack" ]] || continue
  [[ -f "$stack/docker-compose.yml" || -f "$stack/compose.yml" ]] || continue
  log "Starting $(basename "$stack")"
  (cd "$stack" && docker compose up -d)
done
shopt -u nullglob

log "Backing up persistent configuration"
for svc in persistent-files persistent-dirs; do
  systemctl stop "$svc" 2>/dev/null || true
done
/etc/init.d/persistent-files backup
/etc/init.d/persistent-dirs backup

# Verify the critical account/network state actually made it to persistent storage.
for file in /etc/passwd /etc/group /etc/shadow /etc/gshadow /etc/thinstation.custom; do
  [[ -f "/var/prstnt$file" ]] || die "Persistence verification failed: /var/prstnt$file missing."
  cmp -s "$file" "/var/prstnt$file" || die "Persistence verification failed: $file differs from backup."
done
[[ -d /var/prstnt/etc/NetworkManager/system-connections ]] ||
  die "Persistence verification failed: NetworkManager profiles were not backed up."
[[ -d /var/prstnt/etc/sudoers.d ]] ||
  die "Persistence verification failed: sudoers directory was not backed up."

systemctl start persistent-dirs
systemctl start persistent-files

log "Setup complete and persistence verified."
lsblk "$DISK" 2>/dev/null || true

if (( REBOOT )); then
  if (( NON_INTERACTIVE )); then
    reboot
  else
    read -rp "Press Enter to reboot now, or Ctrl-C to leave the system running."
    reboot
  fi
fi
