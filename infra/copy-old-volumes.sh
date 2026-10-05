#!/usr/bin/env bash
# One-time, after the rename to CareerPolaris (ADR 0056): copies each volume of
# the old compose projects (jsa-infra, jsa-app) into the volume of the same
# name under the new ones (careerpolaris-infra, careerpolaris-app), so the new
# stack starts on the old data. Non-destructive: the old volumes are kept, and
# a new volume that already exists is left alone.
#
# The old stack must be stopped first (`make stop-app && make stop-infra` from
# a checkout before the rename), so Postgres is not copied mid-write.
set -euo pipefail

COPY_IMAGE=alpine:3.24.2
OLD_PROJECTS=(jsa-infra jsa-app)

for project in "${OLD_PROJECTS[@]}"; do
  running="$(docker ps -q --filter "label=com.docker.compose.project=${project}")"
  if [ -n "$running" ]; then
    echo "ERROR: the old ${project} stack is still running. Stop it first, from a checkout"
    echo "  before the rename: make stop-app && make stop-infra"
    exit 1
  fi
done

copied=0
for project in "${OLD_PROJECTS[@]}"; do
  new_project="careerpolaris-${project#jsa-}"
  while read -r old; do
    [ -z "$old" ] && continue
    new="${new_project}_${old#"${project}"_}"
    if docker volume inspect "$new" >/dev/null 2>&1; then
      echo "skip: ${new} already exists"
      continue
    fi
    # Labelled as compose would, so compose adopts the volume as its own.
    docker volume create \
      --label "com.docker.compose.project=${new_project}" \
      --label "com.docker.compose.volume=${old#"${project}"_}" \
      "$new" >/dev/null
    docker run --rm --network none -v "${old}:/from:ro" -v "${new}:/to" "$COPY_IMAGE" \
      sh -c 'cp -a /from/. /to/'
    echo "copied: ${old} -> ${new}"
    copied=$((copied + 1))
  done < <(docker volume ls -q --filter "label=com.docker.compose.project=${project}")
done

echo "${copied} volume(s) copied. The old ones are kept; remove them with"
echo "'docker volume rm' once the new stack runs on its data."
