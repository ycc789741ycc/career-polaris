#!/usr/bin/env bash
# Brings up the private link between the edge and the compute side, where this
# place runs one (the `tunnel` profile). Idempotent. Run by `start-infra` after
# the containers report healthy, which for the tunnel means it is signed in.
#
#   serving  Postgres runs here (the droplet): forward the tunnel's port 5432 to Postgres on
#            loopback, so the compute side reaches it and nothing else does.
#   compute  Postgres runs on the other side: wait until it answers across the
#            tunnel, so `start-app`'s migration does not race the link.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ./"${ENV_FILE:-.env}"; set +a

COMPOSE=(docker compose --env-file "${ENV_FILE:-.env}" -f infra/compose.yml)

running() { [ -n "$("${COMPOSE[@]}" ps -q --status running "$1" 2>/dev/null)" ]; }
selected() { "${COMPOSE[@]}" config --services 2>/dev/null | grep -qx "$1"; }

# `check`, before `up`: a tunnel with no key would only ever wait to sign in.
if [ "${1:-}" = "check" ]; then
  if selected tunnel; then
    : "${TUNNEL_AUTH_KEY:?TUNNEL_AUTH_KEY is required where the tunnel profile runs}"
    : "${TUNNEL_HOSTNAME:?TUNNEL_HOSTNAME is required where the tunnel profile runs}"
  fi
  exit 0
fi

if ! running tunnel; then
  exit 0
fi

tunnel() { "${COMPOSE[@]}" exec -T tunnel "$@"; }
tailscale() { tunnel tailscale --socket=/var/run/tailscale/tailscaled.sock "$@"; }

if running postgres; then
  # The tunnel shares the host's network, so loopback is the published port.
  tailscale serve --bg --tcp 5432 "tcp://127.0.0.1:${POSTGRES_PUBLISHED_PORT:-21472}" >/dev/null
  echo "tunnel: forwarding 5432 to Postgres as ${TUNNEL_HOSTNAME}"
  exit 0
fi

: "${POSTGRES_HOST:?}" "${POSTGRES_PORT:?}"
deadline=$(( $(date +%s) + ${TUNNEL_WAIT_SECONDS:-60} ))
until tunnel nc -z -w 3 "$POSTGRES_HOST" "$POSTGRES_PORT" 2>/dev/null; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "ERROR: Postgres at ${POSTGRES_HOST}:${POSTGRES_PORT} does not answer across the tunnel."
    echo "  Is the edge up (make start-infra there), and is POSTGRES_HOST its tunnel address?"
    exit 1
  fi
  sleep 2
done
echo "tunnel: Postgres answers at ${POSTGRES_HOST}:${POSTGRES_PORT}"
