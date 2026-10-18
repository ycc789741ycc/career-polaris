#!/usr/bin/env bash
# Marks an earlier release Latest, which is what rolls production back
# (ADR 0081): the rollout controller deploys the release marked Latest, so on
# its next pass it takes both machines back to this one, in the usual order.
#
#   rollback-release.sh <tag>
#
# Nothing is deleted or edited but which release is Latest, and the next
# `make release` moves Latest forward again. A release whose migrations the
# newer one has already applied cannot run (the older image refuses the newer
# schema); the controller stops before changing anything and says so, and that
# release is fixed forward instead (docs/deploy.md, section 4).
#
# Runs curl on the host rather than in a container, with the operator's own
# GitHub token: GH_TOKEN if set, else `gh auth token`. No image holds it, as
# scripts/tag-release.sh pushes with the operator's own git credentials.
set -euo pipefail
cd "$(dirname "$0")/.."

tag="${1:-}"
if ! [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: name the release to go back to: make rollback-release TAG=v1.2.3 (got '${tag}')."
  exit 1
fi

token="${GH_TOKEN:-}"
if [ -z "$token" ] && command -v gh >/dev/null 2>&1; then
  token="$(gh auth token 2>/dev/null || true)"
fi
if [ -z "$token" ]; then
  echo "ERROR: no GitHub token. Set GH_TOKEN to a token that may write this repository's"
  echo "  releases (contents: write), or sign in with gh."
  exit 1
fi

# owner/repo from origin, over HTTPS or SSH.
repo="$(git remote get-url origin | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##')"
api="https://api.github.com/repos/${repo}"

github() {
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer ${token}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" "$@"
}

if ! release="$(github "${api}/releases/tags/${tag}" 2>&1)"; then
  echo "ERROR: ${repo} has no release ${tag}."
  exit 1
fi
# The release's own id is its first "id" key; its assets' come later.
release_id="$(sed -n 's/^  "id": \([0-9][0-9]*\),$/\1/p' <<<"$release" | head -n 1)"
if [ -z "$release_id" ]; then
  echo "ERROR: could not read ${tag}'s release from GitHub's reply."
  exit 1
fi
if ! grep -q '"name": "release.env"' <<<"$release"; then
  echo "ERROR: ${tag}'s release carries no release.env, so no machine could run it."
  exit 1
fi

if [ "${YES:-}" != "1" ]; then
  read -r -p "Type 'yes' to mark ${tag} Latest; both machines go back to it on the next pass: " ok
  [ "$ok" = "yes" ] || { echo "aborted"; exit 1; }
fi

github -X PATCH "${api}/releases/${release_id}" -d '{"make_latest":"true"}' >/dev/null
echo "${tag} is Latest. The compute machine rolls both machines back to it on its next pass;"
echo "  make rollout-status there shows when it has."
