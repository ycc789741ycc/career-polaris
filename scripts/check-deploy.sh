#!/usr/bin/env bash
# The deployment shape, checked by `make lint` (ADR 0062):
#
#   - every deploy/<machine>/ holds compose.app.yaml and compose.infra.yaml,
#     and each renders: its `extends` name services the bases define, and every
#     variable it reads is one .env.example declares;
#   - a machine's app and infra projects share one network, and have
#     different project names;
#   - .env.example holds nothing about a machine's shape: which services run,
#     ceilings, log rotation, Postgres's sizing, published ports. Those are
#     literals in the machine's files.
#
# `docker compose config` only reads and renders; it starts nothing.
set -euo pipefail
cd "$(dirname "$0")/.."

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# .env.example with every blank filled, so a required variable renders.
sed -E 's/^([A-Z0-9_]+)=$/\1=placeholder/' .env.example > "$work/env"

failed=0
count=0
for dir in deploy/*/; do
  dir="${dir%/}"
  machine="$(basename "$dir")"
  app="$dir/compose.app.yaml"
  infra="$dir/compose.infra.yaml"
  if [ ! -f "$app" ] || [ ! -f "$infra" ]; then
    echo "ERROR: deploy/$machine needs both compose.app.yaml and compose.infra.yaml."; failed=1; continue
  fi
  count=$((count + 1))
  for file in "$app" "$infra"; do
    if ! out="$(docker compose --env-file "$work/env" -f "$file" --profile '*' config -q 2>&1)"; then
      echo "ERROR: $file does not render:"; echo "$out" | sed 's/^/  /'; failed=1
    fi
  done
  net_of() { sed -n '/^networks:/,/^[^ ]/s/^    name: *//p' "$1"; }
  name_of() { sed -n 's/^name: *//p' "$1"; }
  if [ -z "$(net_of "$app")" ] || [ "$(net_of "$app")" != "$(net_of "$infra")" ]; then
    echo "ERROR: deploy/$machine: the app and infra files must name the same default network."; failed=1
  fi
  if [ -z "$(name_of "$app")" ] || [ "$(name_of "$app")" = "$(name_of "$infra")" ]; then
    echo "ERROR: deploy/$machine: the app and infra projects need names of their own."; failed=1
  fi
done

shape='^(COMPOSE_PROFILES|PUBLISHED_BIND_ADDRESS|[A-Z0-9]+_PUBLISHED_PORT|[A-Z0-9]+_MEM_LIMIT|[A-Z0-9]+_CPUS|DOCKER_LOG_[A-Z_]+|POSTGRES_(SHARED_BUFFERS|WORK_MEM|EFFECTIVE_CACHE_SIZE|MAX_CONNECTIONS))='
if grep -qE "$shape" .env.example; then
  echo "ERROR: .env.example sets what belongs in a machine's compose files (ADR 0062):"
  grep -E "$shape" .env.example | cut -d= -f1 | sed 's/^/  /'
  failed=1
fi

[ "$failed" -eq 0 ] || exit 1
echo "deploy: $count machines, each rendering, with .env.example holding none of their shape"
