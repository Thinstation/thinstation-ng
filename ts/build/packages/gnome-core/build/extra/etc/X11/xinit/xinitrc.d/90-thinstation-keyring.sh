# Common to LightDM, agetty/XFCE and agetty/X11/application sessions.
# This is intentionally not a shell profile hook for non-graphical servers.
if [ -n "${DISPLAY:-}" ] && [ -r /etc/thinstation-keyring.functions ]; then
    . /etc/thinstation-keyring.functions
    thinstation_keyring_init || printf 'ThinStation: keyring unavailable; GUI applications requiring it will refuse fallback storage.\n' >&2
fi
