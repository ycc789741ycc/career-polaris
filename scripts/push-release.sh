#!/usr/bin/env bash
# Builds the prod images for every platform the app runs on and pushes them to
# the registry, then writes the release file: each image by digest (ADR 0055).
# CI runs it for a version tag, after every gate has passed on the tagged
# commit (ADR 0060).
#
# The droplet is amd64, and the compute machine may be an arm64 Mac, where an
# amd64 image would run under emulation — slowly, for embeddings. So each image
# is a multi-platform manifest, and its digest names the same release on both.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ./"${ENV_FILE:-.env}"; set +a
: "${RELEASE_REGISTRY:?RELEASE_REGISTRY is required to push a release (e.g. ghcr.io/<owner>)}"
platforms="${RELEASE_PLATFORMS:-linux/amd64,linux/arm64}"
release_file="${RELEASE_FILE:-release.env}"

# A release is a version tag on a commit already on master (ADR 0060): the tag
# names the images, and the digests in the release file name their bytes.
tag="$(git describe --exact-match --tags --match 'v*' HEAD 2>/dev/null || true)"
if ! [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: HEAD carries no version tag like v1.2.3 (got '${tag}'). Tag a commit on master to release it."
  exit 1
fi
if ! git merge-base --is-ancestor HEAD origin/master; then
  echo "ERROR: ${tag} is not on origin/master. Only a commit merged to master is released."
  exit 1
fi

# name, build context
images=("backend backend" "web web" "proxy proxy")

: > "$release_file.tmp"
for entry in "${images[@]}"; do
  read -r name context <<<"$entry"
  ref="${RELEASE_REGISTRY}/careerpolaris-${name}:${tag}"
  echo "release: building and pushing ${ref} for ${platforms}"
  docker buildx build --platform "$platforms" --target prod --tag "$ref" --push "$context"
  digest="$(docker buildx imagetools inspect "$ref" --format '{{.Manifest.Digest}}')"
  upper="$(echo "$name" | tr '[:lower:]' '[:upper:]')"
  echo "CAREERPOLARIS_${upper}_IMAGE=${RELEASE_REGISTRY}/careerpolaris-${name}@${digest}" >> "$release_file.tmp"
done
mv "$release_file.tmp" "$release_file"

echo
echo "release ${tag}, in ${release_file}:"
cat "$release_file"
