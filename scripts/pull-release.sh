#!/usr/bin/env bash
# Pulls a release's images by digest and tags them as this machine's prod
# images, which `start-app` runs (ADR 0055). Neither the droplet nor the
# compute machine builds anything; both run exactly what CI tested and pushed.
#
#   pull-release.sh <release file>    the release.env CI wrote
#
# Pulls anonymously (ADR 0082). The release images are public, so a pull needs
# no credentials, and it is made with an empty Docker config of its own: no
# credential helper runs, so a pull never waits on the macOS Keychain, which
# can hold an unattended rollout until someone is at the screen. The endpoint
# the machine's own config chooses (Docker Desktop's context on the Mac) is
# kept through DOCKER_HOST. A registry that turns private fails the pull at
# once, with the registry's own refusal.
set -euo pipefail
cd "$(dirname "$0")/.."

release_file="${1:-}"
if [ -z "$release_file" ] || [ ! -f "$release_file" ]; then
  echo "ERROR: name the release file CI wrote: make pull-app RELEASE=release.env"
  exit 1
fi

pull_config="$(mktemp -d)"
trap 'rm -rf "$pull_config"' EXIT
echo '{}' > "${pull_config}/config.json"
docker_host="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}"

for name in backend web proxy; do
  upper="$(echo "$name" | tr '[:lower:]' '[:upper:]')"
  ref="$(grep -E "^CAREERPOLARIS_${upper}_IMAGE=" "$release_file" | cut -d= -f2- || true)"
  case "$ref" in
    *@sha256:*) ;;
    *) echo "ERROR: ${release_file} names no digest for careerpolaris-${name} (got '${ref}')."; exit 1 ;;
  esac
  DOCKER_CONFIG="$pull_config" DOCKER_HOST="$docker_host" docker pull --quiet "$ref" >/dev/null
  docker tag "$ref" "careerpolaris-${name}:prod"
  echo "careerpolaris-${name}:prod is ${ref}"
done
