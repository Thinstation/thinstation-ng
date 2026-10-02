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
