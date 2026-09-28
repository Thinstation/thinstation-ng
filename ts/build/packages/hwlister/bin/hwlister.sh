#!/bin/bash

. /etc/thinstation.global

rm -rf /vbe_modes.list /firmware.list /module.list /package.list

firmware_loaded()
{
	if [ "`stat -c '%X' $1`" != "`stat -c '%Z' $1`" ]; then
		return 0
	else
		return 1
	fi
}

module_is_filesystem()
{
	case "$1" in
		*/kernel/fs/*)
			return 0
			;;
	esac
	return 1
}

module_is_dependency()
{
	local module="$1"
	local holders="/sys/module/$module/holders"

	[ -d "$holders" ] || return 1
	find "$holders" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .
}

module_profile_name()
{
	local name="$1"

	name="${name%.zst}"
	name="${name%.xz}"
	name="${name%.gz}"
	name="${name%.ko}"
	printf '%s\n' "$name"
}

warn_unresolved_module()
{
	local module="$1"
	echo "hwlister: warning: loaded module '$module' could not be resolved with modinfo; skipping it" >&2
}

if [ -e /fastboot/firmware ]; then
	fdir=/fastboot/firmware
else
	fdir=/lib/firmware
fi
for firmware in `find $fdir -type f`; do
	if firmware_loaded "$firmware"; then
		firmware=`echo $firmware |cut -d "/" -f4-`
		echo "firmware $firmware" >> /firmware.list
	fi
done

IFS=$'\n'
for firm in `journalctl -xe |grep -e "Direct firmware load" |sed -E 's/[[:alnum:][:punct:][:space:]]+Direct firmware load for //g' |sed -E 's/ failed [[:alnum:][:punct:][:space:]]+//g'`; do
	firm=`echo "$firm" |cut -d "/" -f4-`
	echo "firmware $firm" >> /firmware.list
done
unset IFS

# Record only loaded leaf modules. modprobe will pull their dependencies in
# automatically, so storing every lsmod entry makes profiles unnecessarily
# noisy and fragile as kernel dependency trees change.
tmp_module_list=/module.list.$$
: > "$tmp_module_list"

for module in `lsmod | awk 'NR > 1 {print $1}'`; do
	module_file=`modinfo -F filename "$module" 2>/dev/null`
	if [ "$?" -ne 0 ] || [ -z "$module_file" ]; then
		warn_unresolved_module "$module"
		continue
	fi

	# Filesystems are selected independently by the ThinStation build.
	module_is_filesystem "$module_file" && continue

	# Loaded modules listed in holders/ are dependencies of another loaded
	# module. Keep only leaves; their dependencies will be brought in by modprobe.
	module_is_dependency "$module" && continue

	profile_name=`basename "$module_file"`
	profile_name=`module_profile_name "$profile_name"`
	[ -n "$profile_name" ] && echo "module $profile_name" >> "$tmp_module_list"
done

sort -u "$tmp_module_list" > /module.list
rm -f "$tmp_module_list"

#if [ -e /bin/Xorg ] && [ ! -e /var/log/Xorg.0.log ]; then
#	Xorg -configure
#fi
if [ -e /var/log/Xorg.0.log ]; then
	xdriver=`grep /var/log/Xorg.0.log -e "driver 0" |cut -d\) -f2 |cut -d " " -f3`
	for available in radeon intel geode vmware sis openchrome nv ati nouveau; do
		if [ "$xdriver" == "$available" ]; then
			echo package xorg7-$xdriver >> /package.list
		fi
	done
fi

if [ -e /sys/devices/platform/uvesafb.0/vbe_modes ]; then
	cp /sys/devices/platform/uvesafb.0/vbe_modes /vbe_modes.list
fi

if [ -n "$SERVER_IP" ]; then
	tftp -p -l /module.list -r module.list $SERVER_IP

	if [ -e /package.list ]; then
		tftp -p -l /package.list -r package.list $SERVER_IP
	fi
	if [ -e /vbe_modes.list ]; then
		tftp -p -l /vbe_modes.list -r vbe_modes.list $SERVER_IP
	fi
	if [ -e /firmware.list ]; then
		tftp -p -l /firmware.list -r firmware.list $SERVER_IP
	fi
fi
