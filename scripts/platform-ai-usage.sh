#!/usr/bin/env bash
# What AI has cost (ADR 0064): the platform key's spend today and this month
# against its ceilings, the accounts that spent most of it, spend by task, and
# how far each prompt's estimate is from what calls really cost. Read-only: one
# READ ONLY transaction, run by psql inside the Postgres container, so nothing
# is installed on the host. Accounts appear only as a digest of their id, never
# an address. Needs infra up, on the machine that runs Postgres.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ./"${ENV_FILE:-.env}"; set +a
: "${POSTGRES_SUPERUSER:?}" "${POSTGRES_DB:?}"

COMPOSE=(docker compose --env-file "${ENV_FILE:-.env}" -f "${INFRA_COMPOSE_FILE:?run through make}")

if [ -z "$("${COMPOSE[@]}" ps -q --status running postgres 2>/dev/null)" ]; then
  echo "ERROR: Postgres does not run here. Run this where it does, after: make start-infra"
  exit 1
fi

if [ -z "${PLATFORM_AI_API_KEY:-}" ]; then
  echo "NOTE: PLATFORM_AI_API_KEY is blank here, so the platform's AI is off on this machine."
  echo
fi

"${COMPOSE[@]}" exec -T -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" postgres \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_SUPERUSER" -d "$POSTGRES_DB" -P footer=off \
  -v day_ceiling="${PLATFORM_AI_DAILY_CEILING_USD:-5}" \
  -v month_ceiling="${PLATFORM_AI_MONTHLY_CEILING_USD:-50}" \
  -v quota="${PLATFORM_AI_MONTHLY_QUOTA_USD:-2}" <<'SQL'
BEGIN READ ONLY;

\echo '== The platform key: spent, and held by calls in progress, against its ceilings =='
WITH bounds AS (
  SELECT date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'   AS day_start,
         date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS month_start
)
SELECT 'today (UTC)' AS window,
       round(coalesce(sum(cost_usd), 0), 4) AS spent_usd,
       :'day_ceiling'::numeric AS ceiling_usd,
       round(100 * coalesce(sum(cost_usd), 0) / :'day_ceiling'::numeric, 1) AS pct
  FROM identity.ai_usage_ledger, bounds
 WHERE funding = 'platform' AND occurred_at >= bounds.day_start
UNION ALL
SELECT 'this month',
       round(coalesce(sum(cost_usd), 0), 4),
       :'month_ceiling'::numeric,
       round(100 * coalesce(sum(cost_usd), 0) / :'month_ceiling'::numeric, 1)
  FROM identity.ai_usage_ledger, bounds
 WHERE funding = 'platform' AND occurred_at >= bounds.month_start;

SELECT count(DISTINCT id) AS calls_in_progress,
       round(coalesce(sum(amount_usd), 0), 4) AS held_usd
  FROM limits.spend_reservation
 WHERE expires_at > now();

\echo
\echo '== The 20 accounts that spent most of the platform key this month (by digest) =='
SELECT left(encode(digest(owner_id::text, 'sha256'), 'hex'), 12) AS account,
       count(*) AS calls,
       round(sum(cost_usd), 4) AS spent_usd,
       round(100 * sum(cost_usd) / :'quota'::numeric, 1) AS pct_of_quota
  FROM identity.ai_usage_ledger
 WHERE funding = 'platform'
   AND occurred_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
 GROUP BY owner_id
 ORDER BY sum(cost_usd) DESC
 LIMIT 20;

\echo
\echo '== Spend by task this month, by whose key paid =='
\echo '   priced = false: no published rate, so spent_usd is the high fallback guess.'
SELECT task, funding, is_rate_published AS priced, count(*) AS calls,
       round(sum(cost_usd), 4) AS spent_usd,
       round(avg(cost_usd), 5) AS mean_call_usd
  FROM identity.ai_usage_ledger
 WHERE occurred_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
 GROUP BY task, funding, is_rate_published
 ORDER BY sum(cost_usd) DESC;

\echo
\echo '== Estimates against what calls cost, last 30 days (provider-counted calls only) =='
\echo '   ratio = real / estimated cost: above 1, the estimate was low. Change a'
\echo '   template''s expected_output_tokens, or token_counting in pricing.json, by PR.'
SELECT template_version,
       count(*) AS calls,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY cost_usd / estimated_cost_usd))::numeric, 2) AS median_ratio,
       round((percentile_cont(0.9) WITHIN GROUP (ORDER BY cost_usd / estimated_cost_usd))::numeric, 2) AS p90_ratio,
       round(avg(output_tokens)) AS mean_output_tokens,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY input_tokens::numeric / estimated_input_tokens))::numeric, 2) AS median_input_ratio
  FROM identity.ai_usage_ledger
 WHERE NOT is_estimated
   AND is_rate_published
   AND estimated_cost_usd > 0
   AND estimated_input_tokens > 0
   AND occurred_at >= now() - interval '30 days'
 GROUP BY template_version
 ORDER BY count(*) DESC;

COMMIT;
SQL
