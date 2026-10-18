#!/usr/bin/env bash
# SSH's ProxyCommand for the rollout (ADR 0081): carries the connection to the
# droplet through this machine's tunnel container, whose Tailscale is the only
# way onto the tailnet here. The Mac itself is not on it, so the Mac's own
# OpenSSH client reaches the droplet's sshd through `tailscale nc`, as the
# worker reaches Postgres through the same tunnel.
#
#   rollout-ssh-proxy.sh <host> <port>
set -euo pipefail
cd "$(dirname "$0")/.."

machine="$(cat .machine)"
tunnel="$(docker compose --env-file "${ENV_FILE:-.env}" -f "deploy/${machine}/compose.infra.yaml" ps -q tunnel)"
if [ -z "$tunnel" ]; then
  echo "rollout-ssh-proxy: the tunnel is not running here. Run: make start-infra" >&2
  exit 1
fi
exec docker exec -i "$tunnel" tailscale --socket=/var/run/tailscale/tailscaled.sock nc "$1" "$2"
