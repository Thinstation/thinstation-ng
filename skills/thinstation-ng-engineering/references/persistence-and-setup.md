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

A successful container start does not mean the GitLab web UI is immediately ready.

Observed first-start sequence:

- PostgreSQL, Redis, Gitaly, KAS, and SSH start first.
- Nginx and Workhorse may appear before Rails is ready.
- Puma can spend roughly a minute preloading the Rails application.
- Until Puma creates `/var/opt/gitlab/gitlab-rails/sockets/gitlab.socket`, Workhorse can return `502 Bad Gateway`.

When validating GitLab startup, inspect:

```bash
docker exec gitlab gitlab-ctl status
docker exec gitlab ls -l /var/opt/gitlab/gitlab-rails/sockets/
docker exec gitlab tail -80 /var/log/gitlab/puma/current
docker exec gitlab tail -80 /var/log/gitlab/gitlab-workhorse/current
```

Treat a temporary 502 during first-run initialization as a readiness condition, not immediately as a networking failure. Confirm the Rails socket and retry before changing network/firewall configuration.


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
