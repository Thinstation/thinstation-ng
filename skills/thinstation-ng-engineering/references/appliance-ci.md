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

is not automatically guaranteed to land in the runtime filesystem merely because it exists in the package source tree. Verify packaging mechanics. Runtime `/docker/<stack>/compose...` must actually exist before `setup-docker` can persist or launch it.

Preferred packaging direction is to put files that must land in the runtime root under the package's `build/extra/...` tree, e.g. `build/extra/docker/gitlab-ee/docker-compose.yml`, then validate in the built ISO/live guest.

Always test both NPM and GitLab appliance packaging when changing generic Docker-appliance mechanics.
