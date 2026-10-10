#!/usr/bin/env bash
# Decides whether a `make scan` failure blocks this run (docs/decisions/0063).
#
# The scan reads advisory databases that change every day, so a failure on a
# change that did not touch what is scanned is news about master, not about the
# change. It blocks:
#   - a version tag: nothing is released with a known, fixable finding;
#   - the daily scheduled scan and a manual run of it;
#   - a pull request or a push to master that changes what is scanned:
#     lockfiles, manifests, Dockerfiles, the proxy, the Makefile (it pins the
#     scanner), the exception files, or this gate itself.
# Anything else runs the scan as advice: a failure is reported, not fatal, and
# the daily scan on master owns it.
#
# Writes `blocking=true|false` to $GITHUB_OUTPUT. A pull request is checked out
# as its merge commit and master receives only merges, so the change is the
# diff against the first parent; the checkout needs `fetch-depth: 2`.
set -euo pipefail

SCANNED='^(backend/(uv\.lock|pyproject\.toml|Dockerfile|pip-audit-ignore\.txt)|web/(package\.json|package-lock\.json|Dockerfile)|proxy/.*|Makefile|\.trivyignore\.yaml|\.github/workflows/(ci\.yml|scan\.yml|scan-gate\.sh))$'

decide() {
  case "${GITHUB_EVENT_NAME:-}" in
    schedule | workflow_dispatch)
      echo "true scheduled scan"; return ;;
    push)
      if [[ "${GITHUB_REF:-}" == refs/tags/v* ]]; then
        echo "true version tag"; return
      fi ;;
    pull_request) ;;
    *)
      echo "true unknown event ${GITHUB_EVENT_NAME:-none}"; return ;;
  esac

  if ! git rev-parse --verify --quiet HEAD^1 >/dev/null; then
    echo "true no parent commit to compare with"; return
  fi
  local touched
  touched=$(git diff --name-only HEAD^1 HEAD | grep -E "$SCANNED" || true)
  if [ -n "$touched" ]; then
    echo "true changes what is scanned: $(echo "$touched" | paste -sd ' ' -)"
  else
    echo "false changes nothing the scan reads"
  fi
}

read -r blocking reason <<<"$(decide)"
echo "Scan is $([ "$blocking" = true ] && echo blocking || echo advisory): $reason"
echo "blocking=$blocking" >> "${GITHUB_OUTPUT:-/dev/stdout}"
