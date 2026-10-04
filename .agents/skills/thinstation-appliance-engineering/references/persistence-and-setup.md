# Persistence and setup-docker

## Native ThinStation persistence

`persistent-files` backs up selected files into `/var/prstnt` and restores them on boot. It reads:

- `/etc/persistent-files.conf`
- `/etc/persistent-files.d/*`

`persistent-dirs` does the same recursively for configured directories via:

- `/etc/persistent-dirs.conf`
- `/etc/persistent-dirs.d/*`

Important default persistent files from `base` include:

- `/etc/passwd`
- `/etc/group`
- `/etc/shadow`
- `/etc/gshadow`
- `/etc/thinstation.env`
- `/etc/thinstation.custom`

The Docker/Sudo packages already persist important directories such as NetworkManager system connections, CA anchors, and `/etc/sudoers.d`.

## Critical ordering rule

Do not restart persistence services before backing up freshly changed state.

`persistent-files.service` runs `persistent-files restore` in `ExecStartPre`. Therefore this sequence is wrong during first-run setup:

```bash
systemctl restart persistent-files
/etc/init.d/persistent-files backup
```

It can restore stale `/var/prstnt/etc/shadow` over a newly set password, then back up the stale value again.

Correct pattern:

1. stop persistence monitors
2. apply desired configuration
3. run `persistent-files backup` and `persistent-dirs backup`
4. verify critical source and backup files match
5. start persistence monitors

For critical files, verify `/etc/...` matches `/var/prstnt/etc/...` with `cmp` before reporting success.

## setup-docker design principles

Treat `setup-docker` as an installer/configurator, not a fragile one-shot script.

Requirements:

- Interactive mode derives sane defaults from the live system.
- Show a full proposed configuration and require explicit approval before destructive or network-changing actions.
- Support `--non-interactive --yes` with flags/environment variables for automation.
- Support `--no-reboot` for testing/automation.
- Reuse an existing valid `ts_persistent` VG by default; repartition only when explicitly requested.
- Never destroy storage merely because the script is being rerun.
- Validate required commands up front.
- Make account changes idempotent.
- Validate the resulting persistent backup before success.
- Start compose stacks by looking for compose files, not by iterating every directory such as `lost+found`.

Useful non-interactive inputs include hostname, IP/CIDR, gateway, DNS, search domain, admin user, disk, and precomputed root/admin password hashes. Avoid plaintext passwords in command history.

## User/account handling

This is Fedora-based ThinStation. Do not assume Debian `adduser`/`deluser` commands exist.

Use shadow-utils (`usermod`, `groupmod`, `useradd`, `userdel`) and ensure the needed binaries are in the appliance package.

Prefer renaming the built-in `tsuser` with `groupmod`/`usermod` so it retains intended supplemental groups. Do not casually delete and recreate it.

A sudoers line for a user is:

```text
username ALL=(ALL) NOPASSWD: ALL
```

A leading `%` refers to a group, not a user.

## Persistent storage layout

The Docker appliance uses the `ts_persistent` VG with labels/mounts roughly:

- `prstnt` -> `/var/prstnt`
- `docker` -> `/docker`
- `log` -> `/var/log`
- `docker-data` -> `/var/lib/docker`
- `container-data` -> `/var/lib/containerd`

Do not place immutable compose seeds directly under `/docker`; the persistent `docker` LV mounts there during boot and hides image contents at that path.

Keep immutable compose seeds in a non-mounted runtime path such as:

```text
/usr/lib/thinstation/docker-stacks/<stack>/docker-compose.yml
```

After persistent filesystems are mounted, `setup-docker` copies those seeds into persistent `/docker/<stack>/`. This gives first boot, upgrades, and reruns the same deterministic source of truth.

On rerun, the seed should refresh the persistent compose file before `docker compose up -d`, so changes such as port mappings are applied by container recreation.

`docker-iso-update` loads versioned images from `/mnt/cdrom0/Docker`, records state under `/var/prstnt/docker-image-state`, and can recreate existing compose stacks when image manifests change.

## First-start service timing

A successful container start does not mean the application is immediately ready. Treat temporary startup HTTP failures as readiness signals until the application's own health/listener/socket evidence shows otherwise.

Validate readiness from the application layer before changing network/firewall configuration.

## K3s persistence model

Do not put the live K3s data tree into `persistent-files` or `persistent-dirs`.

Use:

- `/etc/rancher/k3s` -> ThinStation persistence for configuration
- `/var/lib/rancher/k3s` -> dedicated persistent filesystem such as `k3s-data`
- `/var/lib/kubelet` -> ephemeral unless a specific workload proves otherwise

For an AWX/K3s appliance, a practical persistent layout is:

- `prstnt` -> `/var/prstnt`
- `log` -> `/var/log`
- `k3s-data` -> `/var/lib/rancher/k3s`

K3s local-path PVC data then remains on the same persistent K3s volume.

Start K3s after both `persistent-files.service` and `persistent-dirs.service` so restored configuration is complete before K3s reads it.


## Docker appliance storage boot ordering

Stateful Docker appliances need their data filesystems mounted before persistence and container services read them.

The validated generic layout uses a `docker-storage-mount.service` that:

1. activates `ts_persistent`,
2. mounts `prstnt`, `docker`, `log`, `docker-data`, and `container-data`,
3. runs after fastboot,
4. runs before `persistent-files`, `persistent-dirs`, containerd, and Docker.

First-run setup should mount each LV explicitly by device. Do not assume `mount /var/prstnt` will work unless an fstab entry actually exists.

For stateful Docker workloads, a fixed 2 GiB `/var/lib/docker` is too small. The validated generic split assigns roughly 60% of remaining VG space to `docker-data` and the remainder to `container-data`. On a 64 GiB test disk this produced about 35 GiB for Docker state/volumes and 23 GiB for containerd image/snapshot storage.

## Secrets and generated configuration permissions

Scope restrictive umasks narrowly.

A global `umask 077` used while generating a root-only credentials file can accidentally make subsequently rewritten application configuration unreadable to non-root container users. For Wazuh this changed `internal_users.yml` to mode 0600 and prevented the indexer security plugin from initializing.

Use a subshell or explicit mode for secret creation, then set application configuration to the permissions required by the container. Keep root-only secrets root-only; do not weaken them to solve an unrelated bind-mount permission problem.

## ThinStation configuration layering for appliances

Use the native ThinStation configuration chain instead of inventing a second appliance-specific settings framework.

The important runtime order is:

1. defaults,
2. `/thinstation.buildtime`,
3. network/user/runtime configuration,
4. `/etc/thinstation.custom`,
5. package-specific config writer or stack setup hook.

Use `thinstation.conf.buildtime` for portable image/site defaults that are safe to bake into an image. Use `/etc/thinstation.custom` for persistent machine/site overrides. The custom file is itself persisted by the base package, so generic setup tools must preserve settings they do not own.

When a generic setup tool updates `/etc/thinstation.custom`, modify only the variables it owns. Do not replace the whole file. An appliance configurator may therefore safely coexist with network, application, certificate, and other package settings.

Application stack setup hooks may source the ThinStation configuration layers and translate documented variables into native application configuration immediately before service start.

## Runtime variable documentation contract

Every new ThinStation variable consumed by an init script, config writer, first-run installer, firewall fragment, or appliance stack setup hook must be documented by the package that owns it under:

```text
ts/build/packages/<package>/build/conf/
```

Follow the existing package-conf convention: describe what the variable controls, valid forms/values, the default, and any security implications. This makes enabling the package contribute both behavior and its configuration contract.

Do not document secret injection as a normal runtime variable merely because shell sourcing makes it technically possible. Separate variables into:

- non-secret deployment/site settings suitable for buildtime/custom config;
- generated or externally provisioned secrets that belong in protected persistent application state.

For vault-like applications, encryption roots, auth secrets, database passwords, cache passwords, bootstrap tokens, and comparable credentials should not be accepted from `thinstation.conf.buildtime` or `/etc/thinstation.custom` by default.

## Per-stack preparation hooks

For Docker appliance stacks, keep application-specific preparation outside generic `setup-docker`.

A reusable pattern is:

1. seed an immutable stack under `/usr/lib/thinstation/docker-stacks/<stack>/`;
2. copy it to persistent `/docker/<stack>/` after storage mounts;
3. if the persistent stack contains executable `setup.sh`, run it before `docker compose up -d`;
4. let that hook materialize native config, generate first-run secrets, create directories, and validate permissions.

This preserves a generic Docker installer while still allowing sophisticated package-owned initialization.
