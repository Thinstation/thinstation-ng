#!/usr/bin/env bash
set -Eeuo pipefail

STACK=/docker/wazuh
INDEXER_PASSWORD="${INDEXER_PASSWORD:-}"
KIBANASERVER_PASSWORD="${KIBANASERVER_PASSWORD:-}"
API_PASSWORD="${API_PASSWORD:-}"
REBOOT=1
DOCKER_ARGS=()

die(){ echo "ERROR: $*" >&2; exit 1; }
log(){ echo "[setup-wazuh] $*"; }
randhex(){ openssl rand -hex 20; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --indexer-password) INDEXER_PASSWORD="$2"; shift ;;
    --kibanaserver-password) KIBANASERVER_PASSWORD="$2"; shift ;;
    --api-password) API_PASSWORD="$2"; shift ;;
    --no-reboot) REBOOT=0; DOCKER_ARGS+=(--no-reboot) ;;
    *) DOCKER_ARGS+=("$1") ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "Run as root."

if [[ " ${DOCKER_ARGS[*]} " != *" --no-reboot "* ]]; then
  DOCKER_ARGS+=(--no-reboot)
fi
/root/setup-docker.sh "${DOCKER_ARGS[@]}"

[[ -d "$STACK" ]] || die "Wazuh seed stack missing at $STACK"
cd "$STACK"

if [[ -f .credentials ]]; then
  . ./.credentials
else
  INDEXER_PASSWORD="${INDEXER_PASSWORD:-$(randhex)}"
  KIBANASERVER_PASSWORD="${KIBANASERVER_PASSWORD:-$(randhex)}"
  API_PASSWORD="${API_PASSWORD:-$(randhex)}"
  ( umask 077
    cat > .credentials <<CREDS
INDEXER_PASSWORD='$INDEXER_PASSWORD'
KIBANASERVER_PASSWORD='$KIBANASERVER_PASSWORD'
API_PASSWORD='$API_PASSWORD'
CREDS
  )
fi

cat > .env <<ENV
INDEXER_PASSWORD=$INDEXER_PASSWORD
KIBANASERVER_PASSWORD=$KIBANASERVER_PASSWORD
API_PASSWORD=$API_PASSWORD
ENV
chmod 0600 .env .credentials

hash_password() {
  docker run --rm wazuh/wazuh-indexer:4.14.8 \
    bash -lc '/usr/share/wazuh-indexer/plugins/opensearch-security/tools/hash.sh -p "$1"' -- "$1" |
    tail -n 1
}

replace_hash() {
  local user="$1" hash="$2" file="$3" tmp
  tmp="$file.tmp"
  awk -v user="$user" -v hash="$hash" '
    $0 == user ":" { hit=1 }
    hit && /^[[:space:]]*hash:/ { print "  hash: \"" hash "\""; hit=0; next }
    { print }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

if [[ ! -f .passwords-initialized ]]; then
  log "Generating OpenSearch password hashes"
  admin_hash="$(hash_password "$INDEXER_PASSWORD")"
  kibana_hash="$(hash_password "$KIBANASERVER_PASSWORD")"
  replace_hash admin "$admin_hash" config/wazuh_indexer/internal_users.yml
  replace_hash kibanaserver "$kibana_hash" config/wazuh_indexer/internal_users.yml
  chmod 0644 config/wazuh_indexer/internal_users.yml
  touch .passwords-initialized
fi

if [[ ! -s config/wazuh_indexer_ssl_certs/root-ca.pem ]]; then
  log "Generating Wazuh TLS certificates"
  docker compose -f generate-indexer-certs.yml run --rm generator
fi

[[ -f docker-compose.yml ]] || cp docker-compose.yml.in docker-compose.yml

log "Starting Wazuh 4.14.8"
docker compose up -d

log "Waiting for indexer health"
healthy=0
for _ in $(seq 1 60); do
  if docker compose exec -T wazuh.indexer \
      curl -fks -u "admin:$INDEXER_PASSWORD" \
      https://localhost:9200/_cluster/health >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 5
done
(( healthy )) || die "Wazuh indexer did not become healthy"

docker compose ps
printf '\nCredentials are stored root-only in %s/.credentials\n' "$STACK"
printf 'Dashboard: https://%s/\n' "$(hostname -f 2>/dev/null || hostname)"

if (( REBOOT )); then
  reboot
fi
