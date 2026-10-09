#!/usr/bin/env bash
# One pg_dump of the database, streamed into the backup bucket. Read-only on
# the database, idempotent apart from the new object. Every tool runs in a
# pinned container: pg_dump in the Postgres container itself, the upload in
# the AWS CLI image — nothing on the host.
#
# The bucket is a second one, not the app's: the app's key cannot reach it,
# and its lifecycle rule (not this script) decides how long dumps are kept.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ./"${ENV_FILE:-.env}"; set +a
: "${POSTGRES_SUPERUSER:?}" "${POSTGRES_SUPERUSER_PASSWORD:?}" "${POSTGRES_DB:?}"
: "${BACKUP_S3_ENDPOINT_URL:?BACKUP_S3_ENDPOINT_URL is required to back up}"
: "${BACKUP_S3_REGION:?BACKUP_S3_REGION is required to back up}"
: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET is required to back up}"
: "${BACKUP_S3_ACCESS_KEY_ID:?BACKUP_S3_ACCESS_KEY_ID is required to back up}"
: "${BACKUP_S3_SECRET_ACCESS_KEY:?BACKUP_S3_SECRET_ACCESS_KEY is required to back up}"

COMPOSE=(docker compose --env-file "${ENV_FILE:-.env}" -f infra/compose.yml)
AWS_CLI_IMAGE=amazon/aws-cli:2.37.9

if [ -z "$("${COMPOSE[@]}" ps -q --status running postgres 2>/dev/null)" ]; then
  echo "ERROR: Postgres does not run here. Back up where it does (the edge)."
  exit 1
fi

key="${POSTGRES_DB}/$(date -u +%Y%m%dT%H%M%SZ).dump"

# pipefail: a failed dump fails the target even though the upload saw an end.
"${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" postgres \
  pg_dump --format=custom -U "$POSTGRES_SUPERUSER" -d "$POSTGRES_DB" \
| docker run --rm -i --network careerpolaris_net \
    -e AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID" \
    -e AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_ACCESS_KEY" \
    -e AWS_DEFAULT_REGION="$BACKUP_S3_REGION" \
    "$AWS_CLI_IMAGE" s3 cp - "s3://${BACKUP_S3_BUCKET}/${key}" \
      --endpoint-url "$BACKUP_S3_ENDPOINT_URL" --only-show-errors

echo "backed up to ${BACKUP_S3_BUCKET}/${key}"
echo "restore with: make restore-db BACKUP=${key}"
