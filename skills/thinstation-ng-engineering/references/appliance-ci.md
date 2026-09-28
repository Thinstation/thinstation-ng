# Appliance CI and Packaging

## Appliance build pattern

The shared boot2docker profile keeps appliance packages commented. CI selectively enables the appliance being built after copying the profile into the active build tree.

For GitLab EE CI, the established pattern includes:

```bash
sudo ./setup-chroot -e cp -a /build/conf/boot2docker/* /build/.
sudo sed -i 's/^#package gitlab-ee/package gitlab-ee/' ts/build/build.conf
```

Debug-only packages such as OpenSSH should be enabled in the GitLab appliance CI job, not globally in the shared boot2docker profile.

## Docker image export

Appliance packages carry `build/images.conf`. CI runs `ts/bin/export-docker-images` before the ThinStation build so the pinned image is baked into the ISO under the Docker image/manifests tree.

GitLab EE currently uses a pinned upstream image retagged as `thinstation/gitlab-ee:appliance`.

Do not add explicit `dnf install docker` lines to the appliance CI jobs. Those were removed because they bypassed the intended bootstrap/package flow.

## Extra RPM preload queue

CI owns the large preload list through `TS_EXTRA_PORTS`. `install_chroot` appends it to the stage-1 bulk DNF transaction. This keeps generic/local builds lean while preserving fast appliance CI.

Pass environment variables explicitly through sudo, for example:

```bash
sudo env \
  MAX_PARALLEL_DOWNLOADS="$MAX_PARALLEL_DOWNLOADS" \
  MAX_DOWNLOADS_PER_MIRROR="$MAX_DOWNLOADS_PER_MIRROR" \
  TS_EXTRA_PORTS="$TS_EXTRA_PORTS" \
  ./setup-chroot -i
```

## Files passed into the build

Remember the chroot path model. If CI creates `authorized_keys` in the repository root, the ThinStation build parameter must point to `/authorized_keys` inside the chroot, not `/build/authorized_keys`.

When appending to a root-owned file in CI, do not write:

```bash
sudo echo ... >> file
```

because redirection is performed by the unprivileged shell. Use `sudo tee`.

## Appliance compose payload

A source directory such as:

```text
packages/gitlab-ee/docker/gitlab-ee/docker-compose.yml
```

does not automatically land in the runtime filesystem merely because it exists in the package source tree.

For ordinary RPM-backed packages that run `repackage`, `build/extra` is merged into the package root. The GitLab EE and NPM appliance packages are metadata-only packages with effectively empty `.dna` files and no normal `build/install`, so `build/extra` is not sufficient for their runtime assets.

For metadata-only appliance packages, use `build/finalize` to create runtime assets inside the final image. Selected package finalizers are copied into `tmp-tree/finalize` and executed inside the final `tmp-tree` chroot.

Current convention:

- create immutable compose seeds under `/usr/lib/thinstation/docker-stacks/<stack>/docker-compose.yml`
- create package firewall fragments under `/etc/firewall.d/<order><package>`
- let `setup-docker` copy the immutable compose seed into persistent `/docker/<stack>/` after persistent filesystems are mounted

Do not seed compose files directly under the immutable image's `/docker` path because the persistent `docker` LV mounts there during boot and hides them before first-run setup can copy them.

Always test both NPM and GitLab appliance packaging when changing generic Docker-appliance mechanics.

## GitLab appliance ports

Keep appliance SSH and GitLab repository SSH distinct:

- host/MCP OpenSSH: TCP 22
- GitLab container SSH: host TCP 2222 -> container TCP 22
- GitLab HTTP/HTTPS: TCP 80/443

The GitLab compose seed, GitLab advertised shell SSH port, and firewall fragment must agree on 2222. Avoid making only one of those values configurable unless the others are derived from the same source.
