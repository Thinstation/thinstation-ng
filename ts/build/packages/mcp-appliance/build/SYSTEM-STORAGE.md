# System topics and local storage

Top-level navigation is AI Connector, MCP and System. Local configuration has
individual deep-linked System pages. Legacy route names resolve to the new
topics. MCP bootstrap policy belongs under MCP, not System.

Storage distinguishes device capacity, filesystem usage and free LVM extents.
RAM and virtual mounts are separate. Failed or unavailable discovery is never
reported as an empty group or zero capacity.

Supported changes are grow-only: expand an existing PV after its device has
already grown; allocate free VG extents to a mounted ordinary linear LV and
grow ext4/XFS; or grow a plain ext4/XFS filesystem into its larger device.
LVM uses absolute extent targets, not repeatable relative increments. Exact
filesystem geometry comes from native tools, not df metadata overhead.

Changes require an administrator browser session and CSRF verification. A
five-minute single-use preview is bound to that administrator and the exact
device/filesystem identity, topology and allocation. The user must type the
confirmation. The worker serializes changes, rechecks the state, saves LVM
metadata before allocation and verifies final capacity. Metadata backups are
NOT data backups. Keep an independent data backup before applying a change.

Partial failures record completed steps and do not shrink or automatically
undo anything. If allocation succeeded but filesystem growth failed, refresh
and preview filesystem growth instead of allocating the same space again.
Confirmed operations run in a systemd job, independently of the browser page.

Not supported: partition editing, shrinking, creation of PVs/VGs/LVs or mount
points, thin/snapshot/RAID/mirror/cache/encrypted layouts, unmounted filesystems,
shared/exported/partial groups, or taking space away from another mount. The
legacy first-run whole-disk provisioner is separate and requires administrator
authentication; it is not a resize tool.

The mcp-storage-tools recipe supplies native LVM/ext4/XFS programs to future
images. Add lvm2, lvm2-libs, e2fsprogs and xfsprogs to the appliance RPM preload
when building the image. Older running images can lack these tools; the page
explains dependencies and disables unsupported operations. Image assembly and
boot require separate qualification.

Automated tests use synthetic topology reports and mocked mutation commands.
Read-only discovery can be verified on real disks without resizing them. A
live resize should be qualified on disposable storage before production use;
no real disk resize is part of this UI deployment.
