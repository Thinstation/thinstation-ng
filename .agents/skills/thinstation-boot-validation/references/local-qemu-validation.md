# Local QEMU validation

Use the repository's `ts/bin/bt` harness and local QEMU instances as the standard qualification environment.

## Basic evidence

For a booted guest, verify as applicable:

- kernel/initrd reached userspace,
- expected package payload exists,
- expected systemd units are active,
- no unexpected failed units,
- network stack reaches its intended configured state,
- required listeners are present,
- application/container health is ready,
- QGA responds,
- persistent mounts are correct.

Prefer QGA guest execution for automation because it does not depend on guest network configuration.

## Stateful image qualification

1. Create a fresh raw data disk sized for the target.
2. Boot the ISO with that disk.
3. Run first-time setup.
4. Verify the application reaches its declared healthy state.
5. Gracefully power down through QGA/systemd.
6. Confirm QEMU released the raw disk.
7. Boot the same disk again with the same or newly built ISO as appropriate.
8. Verify mounts, generated identity/certificates, data, and application health survive.

## SSH debugging

SSH may be enabled in a dedicated debug/test profile, but it is secondary to QGA. Keep debug credentials/test keys out of committed reusable defaults.

## Web/service debugging order

When a service is unreachable inside a local test guest:

1. check service/container state,
2. check host listeners in the guest,
3. check compose/port mappings,
4. check firewall state,
5. check the application listener/readiness inside the container,
6. only then change network/firewall configuration.

A running container is not proof the application is ready.

## Completion

A build is qualified when every requirement from the normalized target definition has an observable passing check. Do not substitute success on an unrelated deployment environment for local qualification.

## Hot-deploy versus image qualification

Use hot-deploy to shorten UI/service iteration, not to replace image qualification.

Good hot-deploy candidates:
- HTML/CSS/JavaScript;
- service-side API code;
- helper scripts whose dependencies already exist in the guest;
- service configuration that can be regenerated safely.

After copying changed runtime files into a guest, restart only the affected unit and verify it locally from inside the guest before relying on an external browser/client.

Prefer QGA when SSH is unavailable. For larger payloads, expect guest-agent argument/input limits; transfer a compressed archive in bounded chunks or use guest-agent file APIs when available.

A successful hot-deploy does not prove package inclusion, file modes from package construction, unit enablement, boot ordering, persistence restore, or fresh-install behavior. Follow significant hot-deploy work with a normal build and fresh-boot qualification before merge.

## Console and QR validation

For appliance registration banners and QR codes, validate the actual console after userspace reaches steady state. A correct issue file is insufficient if another unit writes to the TTY afterward.

Prefer one console renderer, normally agetty, and generate issue content atomically. On runtime changes, regenerate the issue first, then restart getty once. On boot, order issue generation before getty rather than restarting getty from inside the producer unit.
