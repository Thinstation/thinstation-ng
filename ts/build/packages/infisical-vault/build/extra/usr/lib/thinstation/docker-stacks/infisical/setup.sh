#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

for cfg in /thinstation.buildtime /etc/thinstation.network /etc/thinstation.user /etc/thinstation.runtime /etc/thinstation.custom; do
  [[ -r "$cfg" ]] && . "$cfg"
done

# Capture only the documented, non-secret site knobs from ThinStation config.
CFG_INFISICAL_SITE_URL="${INFISICAL_SITE_URL:-}"
CFG_INFISICAL_BIND_ADDRESS="${INFISICAL_BIND_ADDRESS:-}"
CFG_INFISICAL_HTTP_PORT="${INFISICAL_HTTP_PORT:-}"
CFG_INFISICAL_TELEMETRY_ENABLED="${INFISICAL_TELEMETRY_ENABLED:-}"

# Vault-internal secrets must never be accepted from ThinStation configuration.
unset ENCRYPTION_KEY AUTH_SECRET POSTGRES_PASSWORD REDIS_PASSWORD POSTGRES_USER POSTGRES_DB
unset INFISICAL_SITE_URL INFISICAL_BIND_ADDRESS INFISICAL_HTTP_PORT INFISICAL_TELEMETRY_ENABLED

random_hex() {
  local bytes="${1:?bytes required}"
  od -An -N"$bytes" -tx1 /dev/urandom | tr -d ' \n'
}

random_b64() {
  local bytes="${1:?bytes required}"
  head -c "$bytes" /dev/urandom | base64 | tr -d '\n'
}

if [[ -f .env ]]; then
  set -a
  . ./.env
  set +a
fi

: "${POSTGRES_USER:=infisical}"
: "${POSTGRES_DB:=infisical}"
: "${POSTGRES_PASSWORD:=$(random_hex 32)}"
: "${REDIS_PASSWORD:=$(random_hex 32)}"
: "${ENCRYPTION_KEY:=$(random_hex 16)}"
: "${AUTH_SECRET:=$(random_b64 32)}"
: "${INFISICAL_BIND_ADDRESS:=127.0.0.1}"
: "${INFISICAL_HTTP_PORT:=8080}"
: "${INFISICAL_TELEMETRY_ENABLED:=false}"

[[ -z "$CFG_INFISICAL_BIND_ADDRESS" ]] || INFISICAL_BIND_ADDRESS="$CFG_INFISICAL_BIND_ADDRESS"
[[ -z "$CFG_INFISICAL_HTTP_PORT" ]] || INFISICAL_HTTP_PORT="$CFG_INFISICAL_HTTP_PORT"
[[ -z "$CFG_INFISICAL_TELEMETRY_ENABLED" ]] || INFISICAL_TELEMETRY_ENABLED="$CFG_INFISICAL_TELEMETRY_ENABLED"

HOST_FQDN="$(hostname -f 2>/dev/null || hostname)"
INFISICAL_SITE_URL="${CFG_INFISICAL_SITE_URL:-https://${HOST_FQDN}}"

install -d -m 0700 postgres redis
cat >.env.tmp <<EOF
ENCRYPTION_KEY=${ENCRYPTION_KEY}
AUTH_SECRET=${AUTH_SECRET}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_DB=${POSTGRES_DB}
DB_CONNECTION_URI=postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379
SITE_URL=${INFISICAL_SITE_URL}
TELEMETRY_ENABLED=${INFISICAL_TELEMETRY_ENABLED}
INFISICAL_BIND_ADDRESS=${INFISICAL_BIND_ADDRESS}
INFISICAL_HTTP_PORT=${INFISICAL_HTTP_PORT}
EOF
install -m 0600 .env.tmp .env
rm -f .env.tmp

echo "Infisical vault configuration prepared for ${INFISICAL_SITE_URL}"
