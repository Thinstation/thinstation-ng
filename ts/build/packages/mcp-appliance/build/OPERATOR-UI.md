# Operator-facing MCP and AI access

AI connections identify applications authorized to use the active MCP, not a model vendor or a network tab. Current named access uses independent bearer tokens stored only as SHA-256 digests. Tokens are returned once; revocation rejects new requests, while an existing in-flight request may finish. Existing shared appliance access remains compatible. The named-token registry is separate from target-system credentials in the vault.

## Accurate boundaries

- Named connections currently grant all MCP tools. This implementation does not enforce per-client tool scopes, target filters, read-only mode or approval policies. Setup requires acknowledgment of the actual access.
- Direct access requires client network reachability and certificate trust. Hosted-client selections explain the missing remote path; they do not create a tunnel or public listener.
- Gateway evidence records HTTP status and time, not tool success. Quiet clients are not declared disconnected.
- Local MCP tests perform initialize, initialized notification and tools/list only. No tools/call is issued. The check does not verify a remote application's path or TLS trust.
- Running process, selected version, responding protocol and task readiness are separate. Missing/stale observations are not displayed as stopped.
- Numeric builds are compared only within a matching generation family. Uninstalled catalog entries are not automatically updates.

## Verification

`npm run build` runs ten JavaScript state-transition tests and ten Python token/state tests before compiling Svelte. The feature was also tested with an isolated HTTP handler and temporary token registry on the inspection appliance: unauthenticated access, non-admin access and missing CSRF were rejected; a valid named token reached MCP initialize, revocation denied it, a second token remained valid, and metadata contained no tokens or hashes. This qualification used no production user sessions or client records and executed no tools.

## Fast paired development deployment

`BUILD_MCP_UI=1` packages the frontend and a development-only `_operator` directory containing the corresponding Python web handlers. `operator-release.json` records the exact commit/pipeline and file checksums. The installer verifies the archive checksum and manifest, separates backend files from the static web root, compiles the Python files, then applies a runtime-only systemd drop-in. It preserves the previous persistent `dev-web` directory and never restarts the MCP runtime.

Run `build/install-dev-operator.py --url HTTPS_BUNDLE_URL --source-sha FULL_COMMIT --pipeline PIPELINE_ID` as root on a development appliance. Supply the exact build just verified in CI. Removing `/run/systemd/system/mcp-appliance-web.service.d/50-operator-dev.conf`, reloading systemd and restarting only the web service rolls back the paired overlay. A reboot also removes the runtime-only override and returns to the prior packaged web/backend. Named access metadata remains on disk, but the old ISO cannot authenticate new named tokens until the operator backend is reapplied or a new ISO is deployed.

Normal ISO builds use the package-owned `mcp-operator-web` systemd entrypoint; `_operator` is not included in the static web root unless `BUILD_MCP_UI=1`.

Reference material used for connection guidance: official MCP architecture/transport documentation, VS Code MCP server documentation, and OpenAI Secure MCP Tunnels documentation. Client-side availability and configuration should be checked against the relevant vendor before adding a new setup flow.
