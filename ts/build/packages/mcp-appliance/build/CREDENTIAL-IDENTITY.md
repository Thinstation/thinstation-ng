# Credential-owned login identity

Inventory describes endpoints: alias, address, platform, optional FQDN and groups.
New entries do not require or imply a login username. Credentials contain the
account identity and authentication material; SSH keys have a login-username
metadata field, while AD/password credentials keep the username in their
credential object. AD bare account names become account@domain for SSH; explicit
UPN or DOMAIN\\account names are preserved. SSH server password support and trusted
host keys are still required; this does not add WinRM transport or join a domain.

For a requested capability, resolve compatible credential types and allowed scopes,
then host assignment before group assignment before an existing unrestricted
credential. Equally specific matches fail. A selected credential missing its
username, lacking an active vault authorization, or failing authentication never
falls back to another account or to inventory. Existing explicit legacy key-path
connections retain their old username only when no eligible credential exists.

Both vault and ACME target matching read the persistent inventory used by the
console and runtime. Host aliases, canonical names, addresses, and group assignments
use the same target ranking. The AD DNS provider uses its explicitly selected AD
credential, with target authorization through either host or group metadata.

Core materialization returns non-secret login metadata plus short-lived file paths.
Password/passphrase values are never command arguments or environment values. The
runtime uses SSH -l to separate UPN usernames from destinations, limits authentication
to the selected method, requires known host keys, and cleans temporary material.
Vault unlocks and one-shot grants remain explicit and are never created implicitly.

Deploy the appliance changes together with the compatible MCP runtime changes.
Do not remove old host fields or invent credentials during migration. Existing
SSH credentials without a login username need that field completed in Credentials.
