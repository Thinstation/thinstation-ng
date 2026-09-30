#!/bin/bash

buffer_size()
{
        local dirty writeback buffer
        dirty=`grep -e Dirty: /proc/meminfo |grep -oe "[0-9]*"`
        writeback=`grep -e Writeback: /proc/meminfo |grep -oe "[0-9]*"`
        let buffer=$dirty+$writeback
        echo $buffer
}

_sync()
{
        echo -e "\nSyncronizing the disk"
        local max spid persec progress pct last now counter time freq
        format='\rProgress %4s at %6s Per Second'
        freq=2
        counter=0
        max=`buffer_size`
        last=$max
        sync &
        spid=$!
        while ps -p $spid >/dev/null 2>&1; do
                now=`buffer_size`
                let persec=$last-$now
                let persec=$persec/$freq
                let progress=$max-$now
                let pct=100*$progress/$max
                printf "$format" "${pct}%" "${persec}K"
                last=$now
                sleep $freq
                let counter+=1
        done
        if [ $counter -gt 0 ]; then
                let time=$counter*$freq
                let persec=$max/$time
                printf "$format\n" "100%" "${persec}K"
        fi
        sleep .1
}

if [ -b /dev/sda ]; then
	DRIVE=/dev/sda
	p=""
elif [ -b /dev/nvme0n1 ]; then
	DRIVE=/dev/nvme0n1
	p=p
fi

# Check if the first partition exists
if [ ! -b ${DRIVE}${p}1 ]; then
  # Create partition table
  /sbin/parted $DRIVE --script mklabel gpt

  # Create the 'boot' partition of 4GB
  /sbin/parted $DRIVE --script mkpart primary 1MiB 4GiB

  # Create the 'home' partition of 4GB
  /sbin/parted $DRIVE --script mkpart primary 4GiB 8GiB

  # Create the 'var/log' partition of 4GB
  /sbin/parted $DRIVE --script mkpart primary 8GiB 12GiB

  # Create the 'config' partition with the rest of the space
  /sbin/parted $DRIVE --script mkpart primary 12GiB 100%

  # Wait a bit for the partition table to be recognized
  sleep 2

  # Format the 'boot' partition as VFAT and label it
  /sbin/mkfs.vfat -F 32 -n BOOT ${DRIVE}${p}1

  # Format the 'home' partition as ext4, label it, and force overwrite if necessary
  /sbin/mkfs.ext4 -F -L home ${DRIVE}${p}2

  # Format the '/var/log' partition as ext4, label it, and force overwrite if necessary
  /sbin/mkfs.ext4 -F -L log ${DRIVE}${p}3

  # Format the 'config' partition as ext4, label it, and force overwrite if necessary
  /sbin/mkfs.ext4 -F -L config ${DRIVE}${p}4

  echo "Partitions created and labeled successfully."
  mkdir -p /mnt/boot
  mount ${DRIVE}${p}1 /mnt/boot
  # First, calculate the total size of the source data
  TOTAL_SIZE=$(du -sb /mnt/cdrom0 | cut -f1)

  # Now, use rsync with pv
  rsync -a --progress /mnt/cdrom0/ /mnt/boot/ | pv -lep -s $TOTAL_SIZE > /dev/null

  cd /mnt/boot/boot

  mv initrd initrd-green
  mv vmlinuz vmlinuz-green
  mv lib.squash lib.squash-green

  rsync -a --progress initrd-green initrd-blue
  rsync -a --progress vmlinuz-green vmlinuz-blue
  rsync -a --progress lib.squash-green lib.squash-blue

echo "machine_id=`dbus-uuidgen`" > machine-id

cat > grub2/grub.cfg << 'EOF'
set default=0
set timeout=3

if [ -e $prefix/green ]; then
  set default=1
fi

# Try to read the machine-id file
set machine_id_file="/boot/machine-id"
if [ -f $machine_id_file ]; then
        source $machine_id_file
else
        # Fallback to a default machine-id
        set machine_id="10000000000000000000000000000001"
fi

menuentry 'blue' --class custom --class gnu-linux --class gnu --class os --unrestricted {
    set enable_progress_indicator=1
    linux /boot/vmlinuz-blue splash=off udev.log_priority=3 rd.udev.log_priority=3 systemd.unified_cgroup_hierarchy=1 quiet console=tty1 boot_device=$root machine_id=$machine_id
    initrd /boot/initrd-blue
}

menuentry 'green' --class custom --class gnu-linux --class gnu --class os --unrestricted {
    set enable_progress_indicator=1
    linux /boot/vmlinuz-green splash=off udev.log_priority=3 rd.udev.log_priority=3 systemd.unified_cgroup_hierarchy=1 quiet console=tty1 boot_device=$root machine_id=$machine_id
    initrd /boot/initrd-green
}
EOF

cd /mnt/boot
cat > system.config << 'EOF'
NET_HOSTNAME=splunk-*

TIME_ZONE=America/Los_Angeles
NET_TIME_SERVER=us.pool.ntp.org

MOUNT_0="LABEL=home     /home           auto    x-mount.mkdir,defaults  0       0"
MOUNT_1="LABEL=log     /var/log           auto    x-mount.mkdir,defaults  0       0"
MOUNT_2="LABEL=config     /opt/splunk/etc           auto    x-mount.mkdir,defaults  0       0"

NET_IP_ens192="192.168.19.19/24"
NET_GATEWAY_ens192="192.168.19.2"
NET_DNS1_ens192="192.168.19.2"
#NET_DNS2_ens192="8.8.4.4"
NET_SEARCH_ens192="thinstation.local"
#NET_ROUTE_ens192_1="10.0.0.0/16,192.168.1.254,1"

NET_IP_ens224="192.168.19.20/24"
NET_GATEWAY_ens224="192.168.19.2"
#NET_ROUTE_ens224_1="10.0.0.0/16,192.168.1.254,1"

NET_IP_ens256="192.168.19.21/24"
NET_GATEWAY_ens256="192.168.19.2"
#NET_ROUTE_ens256_1="10.0.0.0/16,192.168.1.254,1"
EOF

  mkdir -p /mnt/home
  mount ${DRIVE}${p}2 /mnt/home

  mkdir -p /mnt/log
  mount ${DRIVE}${p}3 /mnt/log

  mkdir -p /mnt/config
  mount ${DRIVE}${p}4 /mnt/config

  # First, calculate the total size of the source data
  TOTAL_SIZE=$(du -sb /opt/splunk/etc | cut -f1)

  # Now, use rsync with pv
  rsync -a --progress /opt/splunk/etc/ /mnt/config/ | pv -lep -s $TOTAL_SIZE > /dev/null
  rsync -a /home /mnt/home
  rsync -a /var/log/ /mnt/log/

  _sync
#  reboot
else
  echo "The first partition already exists. Exiting without changes."
fi
