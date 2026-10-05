#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

for cfg in /thinstation.buildtime /etc/thinstation.network /etc/thinstation.user /etc/thinstation.runtime /etc/thinstation.custom; do
  [[ -r "$cfg" ]] && . "$cfg"
done

: "${WARPGATE_SSH_PORT:=2222}"
: "${WARPGATE_HTTPS_PORT:=8888}"
: "${INFISICAL_AGENT_PROXY_PORT:=17322}"
: "${INFISICAL_AGENT_PROXY_UNMATCHED_HOST:=block}"
: "${INFISICAL_AGENT_PROXY_POLL_INTERVAL:=60}"
: "${INFISICAL_HOST_URL:=https://vault.example.org}"

# Backward-compatible default: an existing single broker identity can serve SSH.
: "${INFISICAL_SSH_CLIENT_ID:=${INFISICAL_UNIVERSAL_AUTH_CLIENT_ID:-}}"
# HTTP proxy should normally have its own least-privilege machine identity.
: "${INFISICAL_AGENT_PROXY_CLIENT_ID:=}"

mkdir -p data
chown 1000:1000 data
chmod 0700 data

# Migrate the original single-secret filename into the SSH broker secret once.
if [[ -s infisical-client-secret && ! -e infisical-ssh-client-secret ]]; then
  install -m 0600 infisical-client-secret infisical-ssh-client-secret
fi
for secret_file in infisical-ssh-client-secret infisical-agent-proxy-client-secret; do
  [[ -e "$secret_file" ]] || : > "$secret_file"
  chmod 0600 "$secret_file"
done

cat > .env <<EOF
WARPGATE_SSH_PORT=${WARPGATE_SSH_PORT}
WARPGATE_HTTPS_PORT=${WARPGATE_HTTPS_PORT}
INFISICAL_AGENT_PROXY_PORT=${INFISICAL_AGENT_PROXY_PORT}
INFISICAL_AGENT_PROXY_UNMATCHED_HOST=${INFISICAL_AGENT_PROXY_UNMATCHED_HOST}
INFISICAL_AGENT_PROXY_POLL_INTERVAL=${INFISICAL_AGENT_PROXY_POLL_INTERVAL}
INFISICAL_HOST_URL=${INFISICAL_HOST_URL}
INFISICAL_UNIVERSAL_AUTH_CLIENT_ID=${INFISICAL_SSH_CLIENT_ID}
INFISICAL_CLIENT_SECRET_FILE=/run/secrets/infisical-ssh-client-secret
INFISICAL_AGENT_PROXY_CLIENT_ID=${INFISICAL_AGENT_PROXY_CLIENT_ID}
EOF
chmod 0600 .env

if [[ ! -s .admin-password ]]; then
  head -c 48 /dev/urandom | base64 | tr -d '\n' > .admin-password
  printf '\n' >> .admin-password
  chmod 0600 .admin-password
fi

if [[ ! -s data/warpgate.yaml ]]; then
  ADMIN_PASSWORD="$(tr -d '\r\n' < .admin-password)"
  docker run --rm     -e WARPGATE_ADMIN_PASSWORD="$ADMIN_PASSWORD"     -v "$PWD/data:/data"     thinstation/warpgate-infisical:0.29.1     --config /data/warpgate.yaml unattended-setup     --data-path /data     --http-port 8888     --ssh-port 2222     --mysql-port 0     --postgres-port 0
  unset ADMIN_PASSWORD
fi

# Compose uses one env-file for both services. Override the Universal Auth ID for
# the Agent Proxy without exposing either client secret through the environment.
cat > agent-proxy.env <<EOF
INFISICAL_HOST_URL=${INFISICAL_HOST_URL}
INFISICAL_UNIVERSAL_AUTH_CLIENT_ID=${INFISICAL_AGENT_PROXY_CLIENT_ID}
INFISICAL_AGENT_PROXY_UNMATCHED_HOST=${INFISICAL_AGENT_PROXY_UNMATCHED_HOST}
INFISICAL_AGENT_PROXY_POLL_INTERVAL=${INFISICAL_AGENT_PROXY_POLL_INTERVAL}
EOF
chmod 0600 agent-proxy.env

echo "Warpgate admin password is stored root-only in $PWD/.admin-password"
[[ -s infisical-ssh-client-secret ]] || echo "SSH broker Infisical client secret is not configured: $PWD/infisical-ssh-client-secret"
[[ -s infisical-agent-proxy-client-secret ]] || echo "HTTP Agent Proxy Infisical client secret is not configured: $PWD/infisical-agent-proxy-client-secret"
[[ -n "$INFISICAL_AGENT_PROXY_CLIENT_ID" ]] || echo "HTTP Agent Proxy client ID is not configured."
