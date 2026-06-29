#!/usr/bin/env bash
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root."

command -v lsblk >/dev/null || die "lsblk required."
command -v wipefs >/dev/null || die "wipefs required."
command -v parted >/dev/null || die "parted required."
command -v pvcreate >/dev/null || die "lvm2 tools required."
command -v mkfs.ext4 >/dev/null || die "mkfs.ext4 required."

cidr_to_netmask() {
  local cidr="$1"
  local mask=""
  local full_octets=$((cidr / 8))
  local partial_bits=$((cidr % 8))

  for i in 0 1 2 3; do
    if (( i < full_octets )); then
      mask+="255"
    elif (( i == full_octets )); then
      mask+=$(( 256 - 2 ** (8 - partial_bits) ))
    else
      mask+="0"
    fi

    [[ $i -lt 3 ]] && mask+="."
  done

  echo "$mask"
}

valid_user() {
  local user="$1"
  if echo "$user" |grep -e " " -q ; then return 1; fi
}

valid_ipv4() {
  local ip="$1"
  [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1

  IFS=. read -r a b c d <<< "$ip"
  for octet in "$a" "$b" "$c" "$d"; do
    (( octet >= 0 && octet <= 255 )) || return 1
  done
}

valid_cidr() {
  local cidr="$1"
  [[ "$cidr" =~ ^[0-9]{1,2}$ ]] || return 1
  (( cidr >= 1 && cidr <= 32 ))
}

valid_fqdn() {
  local fqdn="$1"

  [[ ${#fqdn} -le 253 ]] || return 1
  [[ "$fqdn" == *.* ]] || return 1
  [[ "$fqdn" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]]
}

ask_required() {
  local var_name="$1"
  local prompt="$2"
  local validator="$3"
  local value=""

  while true; do
    read -rp "$prompt: " value
    [[ -n "$value" ]] || {
      echo "Value is required."
      continue
    }

    if "$validator" "$value"; then
      printf -v "$var_name" '%s' "$value"
      return 0
    fi

    echo "Invalid value: $value"
  done
}

ask_optional_ip() {
  local var_name="$1"
  local prompt="$2"
  local value=""

  while true; do
    read -rp "$prompt [optional]: " value

    if [[ -z "$value" ]]; then
      printf -v "$var_name" '%s' ""
      return 0
    fi

    if valid_ipv4 "$value"; then
      printf -v "$var_name" '%s' "$value"
      return 0
    fi

    echo "Invalid IPv4 address: $value"
  done
}

echo "Creating ThinStation network config"

ask_required NET_HOSTNAME "Enter hostname as FQDN, example docker01.example.com" valid_fqdn
ask_required NET_IP_ADDRESS "Enter static IPv4 address" valid_ipv4
ask_required NET_CIDR "Enter CIDR prefix, example 24" valid_cidr
ask_required NET_GATEWAY "Enter IPv4 gateway" valid_ipv4
ask_required NET_DNS1 "Enter primary DNS server" valid_ipv4
ask_optional_ip NET_DNS2 "Enter secondary DNS server"
read -rp "Enter DNS search domain [derived from hostname]: " NET_DNS_SEARCH

if [[ -z "$NET_DNS_SEARCH" ]]; then
  NET_DNS_SEARCH="${NET_HOSTNAME#*.}"
fi

ask_required A_USER "Enter a username for an administrative user" valid_user
deluser tsuser
adduser $A_USER
echo "Let's update the password for root"
passwd root
echo "%$A_USER ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/$A_USER

ORIG_CON_NAME="Wired connection 1"
CON_NAME="D1"
IP_CIDR="${NET_IP_ADDRESS}/${NET_CIDR}"
CON_TYPE=$(nmcli con show "$ORIG_CON_NAME" |grep -e connection.type |awk '{print $2}')
IFACE=$(nmcli con show "$ORIG_CON_NAME" |grep -e connection.interface-name |awk '{print $2}')

nmcli connection down "$ORIG_CON_NAME" 2>/dev/null || true
nmcli connection delete "$ORIG_CON_NAME" 2>/dev/null || true
nmcli connection delete "$IFACE" 2>/dev/null || true

nmcli connection add \
  con-name "$CON_NAME" \
  type "$CON_TYPE" \
  ifname "$IFACE" \
  ipv4.method manual \
  ipv4.addresses "$IP_CIDR" \
  ipv4.gateway "$NET_GATEWAY" \
  ipv4.dns "$NET_DNS1${NET_DNS2:+,$NET_DNS2}" \
  ipv4.dns-search "$NET_DNS_SEARCH" \
  autoconnect yes

nmcli connection up "$CON_NAME"
hostnamectl set-hostname "$NET_HOSTNAME"

#NET_MASK="$(cidr_to_netmask "$NET_CIDR")"

cat > /etc/thinstation.custom <<EOF
NET_HOSTNAME=${NET_HOSTNAME}
NET_USE_DHCP=Off
EOF

echo ""
echo "Detecting candidate persistent storage disks..."

VG_NAME="ts_persistent"
ROOT_SRC="$(findmnt -n -o SOURCE / || true)"
ROOT_DISK=""
if [[ -n "$ROOT_SRC" ]]; then
  ROOT_DISK="/dev/$(lsblk -no PKNAME "$ROOT_SRC" 2>/dev/null | head -n1 || true)"
fi

mapfile -t CANDIDATES < <(
  lsblk -dn -o NAME,TYPE,SIZE,MODEL |
  awk '$2=="disk"{print "/dev/"$1" "$3" "$4}'
)

FILTERED=()
for line in "${CANDIDATES[@]}"; do
  dev="$(awk '{print $1}' <<< "$line")"
  [[ "$dev" == "$ROOT_DISK" ]] && continue
  FILTERED+=("$line")
done

[[ ${#FILTERED[@]} -gt 0 ]] || die "No candidate persistent storage disks found."

if [[ ${#FILTERED[@]} -eq 1 ]]; then
  DISK="$(awk '{print $1}' <<< "${FILTERED[0]}")"
  echo "Using only detected candidate: $DISK"
else
  echo "Multiple candidate disks found:"
  select choice in "${FILTERED[@]}"; do
    [[ -n "${choice:-}" ]] || continue
    DISK="$(awk '{print $1}' <<< "$choice")"
    break
  done
fi

echo
echo "Selected disk: $DISK"
echo "THIS WILL DESTROY ALL DATA ON $DISK"
read -rp "Type YES to continue: " CONFIRM
[[ "$CONFIRM" == "YES" ]] || die "Aborted."

echo "Stopping Docker if present..."
systemctl stop docker 2>/dev/null || true
systemctl stop containerd 2>/dev/null || true

echo "Unmounting anything currently mounted from $DISK..."
while read -r mp; do
  [[ -n "$mp" ]] && umount -lf "$mp" || true
done < <(lsblk -nr -o MOUNTPOINT "$DISK" | awk 'NF')

echo "Removing old LVM objects on $DISK..."
mapfile -t OLD_PVS < <(pvs --noheadings -o pv_name 2>/dev/null | awk -v d="$DISK" '$1 ~ "^"d {print $1}')
for pv in "${OLD_PVS[@]}"; do
  vg="$(pvs --noheadings -o vg_name "$pv" 2>/dev/null | awk 'NF{print $1}')"
  if [[ -n "$vg" ]]; then
    echo "Removing VG $vg"
    vgchange -an "$vg" || true
    vgremove -ff "$vg" || true
  fi
done

echo "Wiping disk signatures and partition table..."
wipefs -a "$DISK"
sgdisk --zap-all "$DISK" 2>/dev/null || true
parted -s "$DISK" mklabel gpt
parted -s "$DISK" mkpart primary 1MiB 100%
parted -s "$DISK" set 1 lvm on
partprobe "$DISK"
sleep 2

PART="${DISK}1"
[[ -b "$PART" ]] || PART="${DISK}p1"
[[ -b "$PART" ]] || die "Could not find new partition."

echo "Creating LVM..."
pvcreate -ff -y "$PART"
vgcreate "$VG_NAME" "$PART"

lvcreate -y -L 1G -n prstnt "$VG_NAME"
lvcreate -y -L 1G -n docker "$VG_NAME"
lvcreate -y -L 4G -n log "$VG_NAME"
lvcreate -y -L 2G -n docker-data "$VG_NAME"
lvcreate -y -l 100%FREE -n container-data "$VG_NAME"

echo "Formatting filesystems..."
mkfs.ext4 -F -L prstnt "/dev/$VG_NAME/prstnt"
mkfs.ext4 -F -L docker "/dev/$VG_NAME/docker"
mkfs.ext4 -F -L log "/dev/$VG_NAME/log"
mkfs.ext4 -F -L docker-data "/dev/$VG_NAME/docker-data"
mkfs.ext4 -F -L container-data "/dev/$VG_NAME/container-data"

echo "Preparing mount points..."
mkdir -p /var/prstnt /docker /var/lib/docker /var/lib/containerd

if [[ -d /docker && ! -L /docker ]]; then
  if [[ ! -d /docker-inst ]]; then
    mv /docker /docker-inst
  else
    echo "/docker-inst already exists; leaving it in place."
  fi
fi

mkdir -p /docker

echo "Mounting filesystems..."
mount /var/prstnt
mount /docker
mount /var/lib/docker
mount /var/lib/containerd

echo "Loading Docker Images..."
/sbin/docker-iso-update

echo "Copying original /docker contents..."
if [[ -d /docker-inst ]]; then
  cp -a /docker-inst/. /docker/
fi

echo "Building Docker Containers..."
for docker in $(ls /docker -1 |grep -Ev "^lost"); do
	cd /docker/$docker
	docker compose up -d
done

systemctl restart persistent-files
systemctl restart persistent-dirs
/etc/init.d/persistent-files backup
/etc/init.d/persistent-dirs backup

echo "Done."
echo
lsblk "$DISK"
read -rp "Press any key to reboot or Ctrl-C to abort." CONFIRM
reboot
