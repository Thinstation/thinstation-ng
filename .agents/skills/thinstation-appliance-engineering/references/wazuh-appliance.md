# Wazuh Docker appliance

## Validated model

The ThinStation Wazuh appliance uses Wazuh 4.14.8 with pinned offline images:

- `wazuh/wazuh-manager:4.14.8`
- `wazuh/wazuh-indexer:4.14.8`
- `wazuh/wazuh-dashboard:4.14.8`
- `wazuh/wazuh-certs-generator:0.0.4`

The build exports image archives into ISO Docker staging. Runtime setup imports them, generates credentials and TLS certificates, then starts the single-node compose stack.

## Persistent storage

Validated 64 GiB test disk:

- `prstnt` -> `/var/prstnt` (1 GiB)
- `docker` -> `/docker` (1 GiB)
- `log` -> `/var/log` (4 GiB)
- `docker-data` -> `/var/lib/docker` (about 35 GiB)
- `container-data` -> `/var/lib/containerd` (about 23 GiB)

The generic Docker installer allocates about 60% of remaining VG space to Docker data and the rest to containerd. This is important because Wazuh named volumes live under Docker data.

A boot-time `docker-storage-mount.service` activates/mounts the LVs before persistence and container services. Do not rely on fstab entries that are not present.

## Credentials and permissions

`.credentials` under the persistent Wazuh stack is root-only.

Do not leave `umask 077` globally active while rewriting `config/wazuh_indexer/internal_users.yml`. The indexer runs as UID 1000 and requires that bind-mounted file to be readable. The validated setup scopes the secret umask and explicitly sets `internal_users.yml` to 0644.

Symptom of the bug:

```text
FileNotFoundException: .../opensearch-security/internal_users.yml (Permission denied)
Not yet initialized (you may need to run securityadmin)
```

Fix the host-file mode/root cause rather than disabling security.

## Dependencies

The setup script requires OpenSSL for password/credential work. Keep `openssl` as a Wazuh package dependency.

The certificate generator may emit minor utility warnings from its own container. Judge success by generated certs and service health, not by suppressing build/runtime log text.

## Validation contract

A successful test proved:

1. fresh 64 GiB disk partitioned and all five LVs created,
2. offline images imported,
3. setup exited 0,
4. manager and dashboard up,
5. indexer security initialized and health became healthy,
6. credentials and certs persisted,
7. graceful shutdown,
8. same disk booted again with storage mounts active automatically,
9. all three containers returned automatically,
10. BIOS and EFI boot both succeeded.

Use QGA as the primary automation/control path during tests.
