#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

for cfg in /thinstation.buildtime /etc/thinstation.network /etc/thinstation.user /etc/thinstation.runtime /etc/thinstation.custom; do
  [[ -r "$cfg" ]] && . "$cfg"
done

: "${WARPGATE_SSH_PORT:=2222}"
: "${WARPGATE_HTTPS_PORT:=8888}"
: "${INFISICAL_HOST_URL:=https://vault.example.org}"
: "${INFISICAL_UNIVERSAL_AUTH_CLIENT_ID:=}"

mkdir -p data
chmod 0700 data

if [[ ! -f infisical-client-secret ]]; then
  : > infisical-client-secret
fi
chmod 0600 infisical-client-secret

cat > .env <<EOF
WARPGATE_SSH_PORT=${WARPGATE_SSH_PORT}
WARPGATE_HTTPS_PORT=${WARPGATE_HTTPS_PORT}
INFISICAL_HOST_URL=${INFISICAL_HOST_URL}
INFISICAL_UNIVERSAL_AUTH_CLIENT_ID=${INFISICAL_UNIVERSAL_AUTH_CLIENT_ID}
INFISICAL_CLIENT_SECRET_FILE=/run/secrets/infisical-client-secret
EOF
chmod 0600 .env

if [[ ! -s .admin-password ]]; then
  head -c 48 /dev/urandom | base64 | tr -d '\n' > .admin-password
  printf '\n' >> .admin-password
  chmod 0600 .admin-password
fi

if [[ ! -s data/warpgate.yaml ]]; then
  ADMIN_PASSWORD="$(tr -d '\r\n' < .admin-password)"
  docker run --rm \
    -e WARPGATE_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    -v "$PWD/data:/data" \
    thinstation/warpgate-infisical:0.29.1 \
    --config /data/warpgate.yaml unattended-setup \
    --data-path /data \
    --http-port 8888 \
    --ssh-port 2222 \
    --mysql-port 0 \
    --postgres-port 0
  unset ADMIN_PASSWORD
fi

echo "Warpgate admin password is stored root-only in $PWD/.admin-password"
if [[ ! -s infisical-client-secret ]]; then
  echo "Infisical Universal Auth client secret is not configured yet: $PWD/infisical-client-secret"
fi
