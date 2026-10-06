# ACME standing service authorization: review only

This branch adds a policy helper and 17 synthetic tests. It does not enable automatic credential access, change mcp-vault-run, expose an approval endpoint, or install an approval on the appliance. Do not describe this as completed unattended renewal.

The helper binds approval to the full saved certificate configuration, selected inventory host/groups, credential metadata, and encrypted credential bytes. It supports explicit approval and revocation and rejects changed inputs. Runtime verification is designed for the installed ACME worker inside its known systemd unit, not an environment flag. Local root and trusted installed service code remain in the trust boundary.

The development call attempting to modify the credential-release runner was explicitly blocked by tool safety checks. That modification is not included here and was not rerouted through another mechanism. Live authorization, configuration, and credentials were not changed during this work.

Remaining work: integrate the approved policy at credential release; enforce changes/revocation before execution; wire administrator-and-CSRF-protected approval and revoke controls; invalidate standing approval when saving changed settings; preserve existing manual authorization behavior; test the actual worker lifecycle with synthetic credentials; qualify cleanup, cancellation, reboot persistence, and live deployment. Disabling automatic renewal must revoke permission rather than allowing it to revive when re-enabled.

Current tests do not exercise real credential decryption, a running systemd worker, CA issuance, or complete automatic renewal. They cover persistence, exact binding, changed settings/credentials/targets, revocation, stale approvals, file safety, and early command/scope rejection.
