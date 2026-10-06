#!/usr/bin/env bash
# Tags origin/master with the next version and pushes the tag, which is what
# releases (ADR 0060): CI runs the gates on it, then `make push-app`.
#
#   BUMP=patch|minor|major [YES=1] tag-release.sh
#
# Idempotent. If origin/master already carries a version tag on origin, it
# does nothing. If an earlier run tagged it but never pushed, it pushes that
# tag rather than choosing another number. Asks before pushing; YES=1 does not.
#
# Runs git on the host rather than in a container: it pushes with the
# operator's own credentials, which no image should hold. It reads no .env.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+$'

bump="${BUMP:-}"
case "$bump" in
  patch|minor|major) ;;
  *) echo "ERROR: say which part to raise: make release BUMP=patch|minor|major (got '${bump}')."; exit 1 ;;
esac

git fetch --quiet --tags origin
target="$(git rev-parse 'origin/master^{commit}')"
short="$(git rev-parse --short "$target")"
subject="$(git log -1 --format=%s "$target")"
remote_tags="$(git ls-remote --tags --refs origin 'refs/tags/v*' | sed 's#.*refs/tags/##')"

is_on_origin() { grep -qxF "$1" <<<"$remote_tags"; }

# Asks, then tags (unless the tag already exists here) and pushes.
release() {
  local tag="$1"
  if [ "${YES:-}" != "1" ]; then
    read -r -p "Type 'yes' to tag and push ${tag} (this starts the release in CI): " ok
    [ "$ok" = "yes" ] || { echo "aborted"; exit 1; }
  fi
  if ! git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
    git tag -a "$tag" "$target" -m "$tag"
  fi
  git push --quiet origin "refs/tags/${tag}"
  echo
  echo "Pushed ${tag}. CI now runs the gates on it, then releases it."
  echo "When it is green: gh release download ${tag} -p release.env (docs/deploy.md, section 4)."
}

# Already released, or tagged by an earlier run that did not push.
pending=""
for tag in $(git tag --points-at "$target" -l 'v*' | grep -E "$VERSION_PATTERN" || true); do
  if is_on_origin "$tag"; then
    echo "origin/master (${short}) is already released as ${tag}. Nothing to do."
    exit 0
  fi
  pending="$tag"
done
if [ -n "$pending" ]; then
  echo "origin/master (${short}) is tagged ${pending} here, but the tag is not on origin."
  echo "  ${short} ${subject}"
  release "$pending"
  exit 0
fi

# The next version, from the newest one on master.
previous="$(git tag --merged "$target" -l 'v*' | grep -E "$VERSION_PATTERN" \
  | sed 's/^v//' | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1 || true)"
IFS=. read -r major minor patch <<<"${previous:-0.0.0}"
case "$bump" in
  major) major=$((major + 1)); minor=0; patch=0 ;;
  minor) minor=$((minor + 1)); patch=0 ;;
  patch) patch=$((patch + 1)) ;;
esac
next="v${major}.${minor}.${patch}"

if git rev-parse -q --verify "refs/tags/${next}" >/dev/null || is_on_origin "$next"; then
  echo "ERROR: ${next} already exists on another commit. Check the tags before releasing."
  exit 1
fi

if [ -n "$previous" ]; then
  echo "Release ${next} (previous v${previous}, $(git rev-list --count "v${previous}..${target}") commits since) from origin/master:"
else
  echo "Release ${next}, the first, from origin/master:"
fi
echo "  ${short} ${subject}"
release "$next"
