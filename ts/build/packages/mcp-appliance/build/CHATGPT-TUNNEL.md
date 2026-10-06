# ChatGPT private tunnel

The appliance supports one explicitly configured OpenAI Secure MCP Tunnel, separate from named direct HTTP clients. It never imports an existing host's tunnel configuration or secrets. Do not attach another MCP to an in-use tunnel ID without a planned cutover.

## Operator workflow

Open **AI connections > Set up ChatGPT**. Create a dedicated tunnel using OpenAI Platform tunnel settings, associate the intended ChatGPT workspace, and obtain a runtime API key with Tunnels Read + Use. Enter the connection name, tunnel ID (or an OpenAI tunnel URL containing the ID), and key. An OAuth callback URL is not a tunnel configuration.

Save the connection, then choose **Install component and connect**. The initial connect installs the reviewed runtime component with pinned archive checksum and all upstream licenses, then starts only `mcp-openai-tunnel.service`. Open ChatGPT developer-mode app creation, choose Tunnel, and select the same ID.

Current primary sources:
- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://github.com/openai/tunnel-client/releases

## Boundaries

- Fixed OpenAI HTTPS control plane and fixed local MCP target `http://127.0.0.1:8000/mcp`.
- Main MCP polling channel only; automatic private-network/loopback Harpoon target discovery disabled.
- No inbound public port or public listener added. Health is a private Unix socket.
- Management requires an administrator session; writes require CSRF validation.
- Key is write-only and encrypted using the appliance TPM. Systemd supplies it as an encrypted service credential; it is not placed in command arguments or returned by the API. This is a long-lived transport credential, independent of target-vault unlock leases.
- TPM encryption intentionally has no PCR binding, permitting ISO replacement without measured-boot policy churn. TPM reset/replacement requires the key to be entered again. This does not protect a compromised running root account.
- Runtime package v0.0.15 for x86-64 is pinned and checksum-verified. Updating the reviewed version requires a code change and validation, not an unbounded download of latest.
- The current tunnel exposes all tools of the selected MCP, subject to existing target and vault controls. It does not add per-client tool/host policies.
- Tool requests/results travel through OpenAI; private connectivity is not a local-data guarantee.

## State and lifecycle

Process liveness and local readiness do not establish OpenAI connectivity. Green **Connected to OpenAI** requires recent authenticated control-plane poll evidence. Last queued request and last response accepted are separate observations. They can originate from any OpenAI context permitted to use the tunnel, not necessarily a specific ChatGPT conversation. Observations cover the current process run.

Disconnect stops this appliance's tunnel and removes its persistent enabled marker. It does not stop the MCP or revoke a key/tunnel in OpenAI. Settings may be edited only while disconnected. Config and encrypted key are promoted atomically. Saved profiles do not connect automatically until explicitly requested.

ISO builds install and enable the conditional unit. Development overlays place the unit in `/run/systemd/system` and pair its Python helper with the same backend release. The development overlay does not start a tunnel and reverts on reboot. Keep the existing production CLI tunnel running throughout this appliance's development.
