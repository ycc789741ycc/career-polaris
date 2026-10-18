#!/usr/bin/env bash
# Waits until every app service this machine runs is up and stays up (ADR
# 0081). `start-app` returns once compose has started the containers; this
# says they work: each is running (and healthy, if it has a health check),
# then still running, with no new restart, CHECK_APP_SETTLE_SECONDS later.
# Names any that is not, and fails after CHECK_APP_TIMEOUT_SECONDS.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose --env-file "${ENV_FILE:-.env}" -f "${APP_COMPOSE_FILE:?run through make}")
timeout="${CHECK_APP_TIMEOUT_SECONDS:-180}"
settle="${CHECK_APP_SETTLE_SECONDS:-15}"
deadline=$(( $(date +%s) + timeout ))

# The services `start-app` starts: profile-only one-offs (migrate) are not.
services="$("${COMPOSE[@]}" config --services)"

# One line per service: "<service> <container id> <state> <restarts>", where
# state is the health status if it has a check, else the container's status.
snapshot() {
  local service id
  for service in $services; do
    id="$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null | head -n 1)"
    if [ -z "$id" ]; then
      echo "$service - missing 0"
      continue
    fi
    # `index`, because a container with no health check has no Health key,
    # and reading .State.Health directly fails the whole template.
    docker inspect -f "$service {{.Id}} {{if index .State \"Health\"}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}} {{.RestartCount}}" "$id"
  done
}

all_up() { ! awk '$3 != "running" && $3 != "healthy" { found = 1 } END { exit !found }' <<<"$1"; }

while :; do
  before="$(snapshot)"
  if all_up "$before"; then
    sleep "$settle"
    after="$(snapshot)"
    if [ "$before" = "$after" ]; then
      echo "check-app: $(wc -l <<<"$after" | tr -d ' ') services up: $(awk '{ printf "%s%s", sep, $1; sep = ", " }' <<<"$after")"
      exit 0
    fi
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "ERROR: the app did not come up in ${timeout}s:"
    awk '$3 != "running" && $3 != "healthy" { print "  " $1 ": " $3 } $3 == "running" || $3 == "healthy" { print "  " $1 ": " $3 ", restarts " $4 }' <<<"$(snapshot)"
    echo "  make logs shows why."
    exit 1
  fi
  sleep 2
done
