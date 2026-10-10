#!/usr/bin/env bash
# DESTRUCTIVE: replaces a database's contents with a dump from the backup
# bucket. Asks first. Stop the app before restoring the live database.
#
#   restore-db.sh <key> [database]   database defaults to POSTGRES_DB
#
# Restoring into another database checks a backup without touching the live
# one: create it first, as the superuser, then restore into it.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ./"${ENV_FILE:-.env}"; set +a
key="${1:-}"
target="${2:-}"
target="${target:-${POSTGRES_DB:?}}"
if [ -z "$key" ]; then
  echo "ERROR: name the dump: make restore-db BACKUP=<key> (backup-db printed it)."
  exit 1
fi
: "${POSTGRES_SUPERUSER:?}" "${POSTGRES_SUPERUSER_PASSWORD:?}"
: "${BACKUP_S3_ENDPOINT_URL:?}" "${BACKUP_S3_REGION:?}" "${BACKUP_S3_BUCKET:?}"
: "${BACKUP_S3_ACCESS_KEY_ID:?}" "${BACKUP_S3_SECRET_ACCESS_KEY:?}"

COMPOSE=(docker compose --env-file "${ENV_FILE:-.env}" -f "${INFRA_COMPOSE_FILE:?run through make}")
AWS_CLI_IMAGE=amazon/aws-cli:2.37.9

if [ -z "$("${COMPOSE[@]}" ps -q --status running postgres 2>/dev/null)" ]; then
  echo "ERROR: Postgres does not run here. Restore where it does (the edge)."
  exit 1
fi

if [ "${RESTORE_CONFIRMED:-}" != "yes" ]; then
  read -r -p "This replaces everything in database '${target}' with ${key}. Type 'yes' to continue: " ok
  [ "$ok" = "yes" ] || { echo "aborted"; exit 1; }
fi

docker run --rm --network "${NETWORK:?run through make}" \
    -e AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_ACCESS_KEY" \
    -e AWS_DEFAULT_REGION="$BACKUP_S3_REGION" \
    "$AWS_CLI_IMAGE" s3 cp "s3://${BACKUP_S3_BUCKET}/${key}" - \
      --endpoint-url "$BACKUP_S3_ENDPOINT_URL" --only-show-errors \
| "${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" postgres \
    pg_restore --clean --if-exists --single-transaction --exit-on-error \
      -U "$POSTGRES_SUPERUSER" -d "$target"

echo "restored ${key} into ${target}"
