#!/usr/bin/env bash
# Installs or removes the rollout controller's launchd agent (ADR 0081), on
# the machine whose deploy/<machine>/ holds a rollout file.
#
#   install-rollout.sh install     write the agent for this checkout, load it
#   install-rollout.sh uninstall   unload and remove it
#   install-rollout.sh loaded      exit 0 when the agent is loaded
#
# Installing again replaces the agent in place, after a release changed its
# template. Removing it stops future passes and leaves both machines running
# what they run. launchd is macOS's and runs on the host, so this cannot run
# in a container.
set -euo pipefail
cd "$(dirname "$0")/.."

LABEL=com.careerpolaris.rollout
AGENT="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"
INTERVAL_MINUTES=5

machine="$(cat .machine 2>/dev/null || true)"
template="deploy/${machine}/rollout.plist"

loaded() { launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; }

case "${1:-}" in
  install)
    if [ "$(uname -s)" != Darwin ]; then
      echo "ERROR: the agent is launchd's, on macOS; this is $(uname -s)."
      exit 1
    fi
    if [ ! -f "deploy/${machine}/rollout" ] || [ ! -f "$template" ]; then
      echo "ERROR: this machine (${machine:-none}) runs no rollout."
      exit 1
    fi
    mkdir -p .rollout "$(dirname "$AGENT")"
    checkout="$(pwd -P)"
    awk -v checkout="$checkout" -v step="$INTERVAL_MINUTES" '
      $0 == "@INTERVALS@" {
        for (minute = 0; minute < 60; minute += step)
          printf "    <dict><key>Minute</key><integer>%d</integer></dict>\n", minute
        next
      }
      { gsub(/@CHECKOUT@/, checkout); print }' "$template" > "${AGENT}.tmp"
    plutil -lint "${AGENT}.tmp" >/dev/null
    if loaded; then
      launchctl bootout "${DOMAIN}/${LABEL}"
    fi
    mv "${AGENT}.tmp" "$AGENT"
    launchctl bootstrap "$DOMAIN" "$AGENT"
    echo "install-rollout: ${LABEL} runs make roll-out in ${checkout} every ${INTERVAL_MINUTES} minutes and on wake."
    ;;
  uninstall)
    if loaded; then
      launchctl bootout "${DOMAIN}/${LABEL}"
    fi
    rm -f "$AGENT"
    echo "uninstall-rollout: ${LABEL} removed; both machines keep running what they run."
    ;;
  loaded)
    loaded ;;
  *)
    echo "usage: install-rollout.sh install | uninstall | loaded"
    exit 1 ;;
esac
