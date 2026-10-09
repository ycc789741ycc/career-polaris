#!/usr/bin/env bash
# Refuses to act on a stack another checkout started (ADR 0062). Run by every
# make target that starts, stops or replaces containers or data, before it does.
#
# Compose labels each container with the directory of the first file it was
# started from (com.docker.compose.project.working_dir): a folder of deploy/ in
# the checkout that started it, or, for a stack started before ADR 0062, the
# checkout itself or its infra/. Two clones on one host — the deployment and a
# development one — use different machines, so different project names, and
# never meet here. A clone pointed at the other's machine would; this stops it.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${APP_PROJECT:?run through make}" "${INFRA_PROJECT:?run through make}"

here_logical="$(pwd)"
here_physical="$(pwd -P)"

failed=0
for project in "$APP_PROJECT" "$INFRA_PROJECT"; do
  while read -r dir; do
    [ -z "$dir" ] && continue
    case "$dir" in
      "$here_logical"|"$here_logical"/*|"$here_physical"|"$here_physical"/*) ;;
      *)
        echo "ERROR: $project was started from another checkout: $dir"
        echo "  Run make there, or give this checkout its own machine in .machine."
        failed=1 ;;
    esac
  done < <(docker ps -a --filter "label=com.docker.compose.project=$project" \
             --format '{{.Label "com.docker.compose.project.working_dir"}}' | sort -u)
done
exit "$failed"
