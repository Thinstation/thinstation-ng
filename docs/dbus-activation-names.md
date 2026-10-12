# D-Bus activation filename policy

The dbus package's finalizer runs `bash /build/normalize-dbus-activation /`
inside the assembled image, after selected package payloads have been copied.
The helper stays in the build directory and is removed with build-time files.
It does not modify RPMs, source package payloads, systemd unit files, or D-Bus
policy. No Python runtime is added to the image.

For both vendor directories, `/usr/share/dbus-1/services` (session bus) and
`/usr/share/dbus-1/system-services` (system bus), the canonical filename is the
record's `[D-BUS Service]` `Name` plus `.service`. The public name, Exec, User,
SystemdService, comments, permissions, ownership, and file contents are retained.

Before changing a filename, the helper inventories providers separately for
each bus. It also checks `/usr/local/share/dbus-1` and, for the system bus,
`/etc/dbus-1/system-services` and `/run/dbus-1/system-services`. These other
locations are collision guards only and are never renamed. Both duplicate
advertised names and occupied canonical filenames prevent a rename. Occupied
includes dangling symlinks and directories. Two noncanonical providers do not
compete for a free canonical filename: neither is chosen automatically.

Malformed or unreadable records, symbolic activation records, or non-plain
service directories make that bus inventory uncertain. Its mismatched vendor
records are left unchanged with visible warnings, rather than guessing whether
another provider exists. Hidden .service records are included. Names are
validated as well-known bus names and limited to a filesystem-safe length.
Already-canonical names remain untouched. A no-clobber, no-target-directory move
provides an additional destination-race guard. Running the helper again is safe.

The build log records every rename and skipped candidate. To preview an image
without modifications:

```sh
bash ts/build/packages/dbus/build/normalize-dbus-activation --dry-run /path/to/image
```

This is an image-snapshot policy for standard image-wide directories, not a
runtime preferred-application selector. It does not inspect custom servicedir
XML, user XDG data paths, downloaded external .pkg archives, or packages added
later. Such deployments must resolve their provider-selection policy separately.
Future additions should be evaluated as part of the final image, not normalized
independently during repackage where collisions would be invisible.

Tests in `tests/library_payloads/test_dbus_activation.py` run under the existing
CI test gate. They cover both buses, collisions including two noncanonical
providers, symlinks, directory and destination-race handling, malformed names,
metadata preservation, repeated invocation, BusyBox mv, the six observed XFCE
mappings, and activation through a private D-Bus with an isolated test provider.
The tests do not restart or reconfigure the desktop/system message bus.
