#!/usr/bin/env bash
# Pulls a release's images by digest and tags them as this machine's prod
# images, which `start-app` runs (ADR 0055). Neither the droplet nor the
# compute machine builds anything; both run exactly what CI tested and pushed.
#
#   pull-release.sh <release file>    the release.env CI wrote
#
# A private registry needs `docker login` on this machine once, with a token
# that may only read packages.
set -euo pipefail
cd "$(dirname "$0")/.."

release_file="${1:-}"
if [ -z "$release_file" ] || [ ! -f "$release_file" ]; then
  echo "ERROR: name the release file CI wrote: make pull-app RELEASE=release.env"
  exit 1
fi

for name in backend web proxy; do
  upper="$(echo "$name" | tr '[:lower:]' '[:upper:]')"
  ref="$(grep -E "^CAREERPOLARIS_${upper}_IMAGE=" "$release_file" | cut -d= -f2- || true)"
  case "$ref" in
    *@sha256:*) ;;
    *) echo "ERROR: ${release_file} names no digest for careerpolaris-${name} (got '${ref}')."; exit 1 ;;
  esac
  docker pull --quiet "$ref" >/dev/null
  docker tag "$ref" "careerpolaris-${name}:prod"
  echo "careerpolaris-${name}:prod is ${ref}"
done
