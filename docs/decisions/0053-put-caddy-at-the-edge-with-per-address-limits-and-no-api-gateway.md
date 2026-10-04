# 0053. Caddy is the edge, with per-address limits and no API gateway

**Status:** Accepted — 2026-10-05.

## Context

On the droplet (ADR 0051), something has to:

- terminate TLS;
- serve the SPA and the api to browsers;
- and, now that the app is on the internet, keep one client from taking it
  down.

The api had no limit by client address. The only limit was the sign-in
lockout, which counts failures per account, so a flood spread over many
accounts never tripped it. Every `/auth/register` and `/auth/sign-in` runs
Argon2id (19 MiB, two passes), and the droplet has one vCPU. Uploads were
checked for size only once uvicorn had read them, and a slow client could
hold one of uvicorn's few connections.

There is no domain yet. Files move from MinIO to DigitalOcean Spaces, whose
keys can be limited to one bucket. The database needs backups that do not
live on the droplet.

## Decision

- **Caddy, built with `caddy-ratelimit`**, as the `proxy` service
  (`proxy/`, image `jsa-proxy:prod`). It runs only where `COMPOSE_PROFILES`
  names `proxy`, so development never binds 80 or 443.
  - Caddy 2.11.6 and the plugin's commit are pinned. The plugin's last tag
    predates the Caddy it builds against.
  - It runs as a non-root user, read-only, with every capability dropped and
    `no-new-privileges`. Ports 80 and 443 open through the
    `ip_unprivileged_port_start` sysctl. A file capability on the binary would
    not do: `no-new-privileges` refuses to execute such a binary, so the image
    copies it without one.
- **One origin.** `/api/*` goes to the api, everything else to `web`. The
  refresh cookie stays `SameSite=Strict`, and nothing needs CORS.
  `SITE_HOSTNAME` is required where the proxy runs, and its start fails
  without it. Until there is a domain, it is `<droplet-ip>.sslip.io`.
- **Limits Caddy can see, per connection address.** Caddy is the edge, so a
  client's `X-Forwarded-For` is never believed.
  - Bodies are capped at `EDGE_MAX_BODY_SIZE` (11 MB) and refused with 413
    before the api reads them.
  - Header, body and idle timeouts are set. There is no write timeout,
    because the résumé chat streams.
  - `/api/v1/auth/*` takes `EDGE_AUTH_REQUESTS_PER_MINUTE` (10) per address,
    and everything takes `EDGE_REQUESTS_PER_MINUTE` (300). Past either, the
    answer is 429 with `Retry-After`.
- **No separate API gateway.** What only the app can see, the account, is
  limited in the app (Phase 12, "Limit what one account can do").
- **Spaces for files, with a key scoped to the app's bucket.**
  `ObjectStore.ensure_bucket` asks `HeadBucket` about its own bucket instead
  of listing every bucket, which such a key may not do.
- **Backups to a second bucket.**
  - `make backup-db` streams `pg_dump --format=custom` from the Postgres
    container into it, through the pinned AWS CLI image.
  - `make restore-db BACKUP= [RESTORE_DB=]` is destructive, asks first, and
    is a dependency of nothing.
  - The bucket's lifecycle rule decides how long dumps are kept. A host cron
    on the droplet runs the backup nightly.
- **`make lint` validates the Caddyfile** with the proxy image, and `scan`
  covers that image like the others.

## Consequences

Easier:

- One small process (about 30 MB) does TLS, certificates, routing and the
  per-address limits. Nothing is added to the api for them.
- Uploads over the cap, request floods on sign-in and slow clients stop at
  the edge.
- A backup is one target, reads only the database, and lives off the
  droplet with a key the app does not hold.
- A restore can be rehearsed into a scratch database without stopping
  anything.

Harder:

- **The proxy is built, not pulled.** It is one more image to build, scan and
  release. Moving to a newer Caddy means changing the pinned version and
  the plugin's commit together.
- **Users behind one address share a limit.** That includes an office or a
  campus NAT. 10 requests a minute to `/auth/*` can be too few for a
  classroom signing up at once, and it is a setting.
- **Nothing on the droplet stops a flood the droplet cannot absorb.** That
  needs a proxy in front, such as Cloudflare's, which needs a domain.
- **Google sign-in waits for a domain of our own.** Its consent screen
  wants one we can verify.
- **Exports are kept with no expiry.** They live under each user's prefix,
  which a lifecycle rule cannot match. Expiring them would also break
  reusing an unchanged export.
- **Restoring the live database means stopping the app,** because the
  restore runs in one transaction with `--clean`.

## Alternatives considered

- **An API gateway (Kong, Tyk, APISIX).** It would add 100–500 MB on a 2 GB
  droplet, one more thing to run, and a database or config store of its
  own. Everything it would do here, Caddy does, except per-account quotas,
  which a gateway cannot see without parsing our tokens.
- **nginx.** Its `limit_req` is built in, but certificates would need
  certbot and a renewal timer beside it. Caddy does ACME itself.
- **Limiting in the api only.** Every refused request would still cost a
  uvicorn connection, the body would already be read, and Argon2id floods
  would reach the api.
- **Managed backups (DigitalOcean's droplet backups).** They snapshot the
  whole disk weekly, with Postgres's files mid-write. A logical dump is
  consistent, smaller, and restores into another database.
- **Mounting the Docker socket into a backup container.** It would give the
  container root on the host. Two pinned containers joined by a pipe need
  nothing of the sort.
