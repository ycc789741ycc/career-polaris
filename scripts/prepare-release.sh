#!/usr/bin/env bash
# Readies this machine for a release while the old one still runs (ADR 0081):
# everything that can fail happens here, before the rollout stops anything.
#
#   prepare-release.sh <release file>
#
#   1. refuses a checkout with local changes: a deployed checkout is never
#      edited, and an edit there is drift to report, not to overwrite;
#   2. checks out the release's tag, detached, so the compose files, Makefile
#      and scripts are the release's own;
#   3. pulls its images by digest (`pull-app`), checks .env names every
#      setting it needs (`check-env`), and checks the schema is one its images
#      know (`check-schema`), which stops a rollback past a migration here.
#
# Idempotent: preparing the release a machine already runs changes nothing.
# Only a deployed machine prepares a release; local and ci build their own.
#
# The body is one function, read whole before it runs, because step 2
# rewrites this very file.
set -euo pipefail

prepare() {
  cd "$(dirname "$0")/.."
  local file="${1:-}"
  if [ -z "$file" ] || [ ! -f "$file" ]; then
    echo "ERROR: name the release file: make prepare-release RELEASE=release.env (got '${file}')."
    return 1
  fi

  local version
  version="$(sed -n 's/^RELEASE_VERSION=//p' "$file")"
  if ! [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: ${file} names no RELEASE_VERSION like v1.2.3 (got '${version}')."
    return 1
  fi

  local machine
  machine="$(cat .machine 2>/dev/null || true)"
  case "$machine" in
    '') echo "ERROR: .machine is missing; a deployed machine names itself there."; return 1 ;;
    local|ci) echo "ERROR: ${machine} builds its own images; only a deployed machine prepares a release."; return 1 ;;
  esac

  local changes
  changes="$(git status --porcelain --untracked-files=no)"
  if [ -n "$changes" ]; then
    echo "ERROR: this checkout has local changes, and a deployed checkout is never edited:"
    echo "$changes" | sed 's/^/  /'
    echo "  Put them in a pull request, then git checkout -- . here."
    return 1
  fi

  git fetch --quiet --tags origin
  if ! git rev-parse -q --verify "refs/tags/${version}^{commit}" >/dev/null; then
    echo "ERROR: origin has no tag ${version}."
    return 1
  fi

  # release.env is git-ignored, so the checkout leaves it alone.
  if [ "$(cd "$(dirname "$file")" && pwd -P)/$(basename "$file")" != "$(pwd -P)/release.env" ]; then
    cp "$file" release.env.tmp && mv release.env.tmp release.env
  fi
  git -c advice.detachedHead=false checkout --quiet --detach "refs/tags/${version}"

  make --no-print-directory pull-app RELEASE=release.env
  make --no-print-directory check-env
  make --no-print-directory check-schema
  echo "prepare-release: ${machine} is ready for ${version}"
}

prepare "$@"
exit
