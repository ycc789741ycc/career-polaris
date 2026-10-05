# Deploying CareerPolaris: the droplet and the compute machine

The app runs in two places (ADR 0051):

| Place | Runs | `COMPOSE_PROFILES` |
|---|---|---|
| **Edge**: a DigitalOcean droplet, 1 vCPU, 2 GB | Caddy (ADR 0053), `web`, `api`, Postgres, the tunnel | `edge,proxy,tunnel` |
| **Compute**: the operator's own machine | `worker`, `crawler`, the tunnel | `compute,tunnel` |

Files live in a DigitalOcean Spaces bucket, which both places reach. The
compute side reaches Postgres through a Tailscale tunnel that it dials out
on, so it opens no inbound port. While the compute machine is off, work the
user starts is queued and runs when it is back (ADR 0052).

Every command below is a `make` target, as everywhere in this repo. A host
needs Docker and `make`, and nothing else.

## 1. Once: accounts and buckets

1. **Tailscale.**
   - Create a tailnet.
   - Under Settings → Keys, make two auth keys: reusable, pre-approved,
     tagged `tag:careerpolaris-edge` and `tag:careerpolaris-compute`. For a server, turn off key
     expiry on the machines once they join.
   - Restrict the tailnet to what the app needs. In the access policy, allow
     only `tag:careerpolaris-compute` to reach `tag:careerpolaris-edge:5432`:

     ```json
     {
       "tagOwners": {"tag:careerpolaris-edge": ["autogroup:admin"], "tag:careerpolaris-compute": ["autogroup:admin"]},
       "grants": [{"src": ["tag:careerpolaris-compute"], "dst": ["tag:careerpolaris-edge"], "ip": ["tcp:5432"]}]
     }
     ```
2. **Spaces.** In one region, create two private buckets:
   - **The app's**, e.g. `careerpolaris-files`, with a limited-access key
     that reads and writes only this bucket. The app never lists buckets, so
     a key scoped to one bucket is enough. Leave it with no lifecycle rule:
     a résumé export is reused while its version is unchanged, so an expired
     file would leave a link to nothing.
   - **The backups**, e.g. `careerpolaris-backups`, with its own
     limited-access key, and a lifecycle rule that expires objects after the
     number of days you want to keep, for example 30.
3. **Images.** Every push to `master` that passes CI is released (ADR 0055).
   - CI builds the prod images for amd64 and arm64 and pushes them to
     `ghcr.io/<owner>/careerpolaris-{backend,web,proxy}`.
   - The run's summary, and its `release-<sha>` artifact, hold `release.env`,
     which names each image by digest.
   - Neither machine builds anything. If the packages are private, give each
     machine a classic token with only `read:packages`, once:
     `docker login ghcr.io -u <user>`.

## 2. The droplet

1. **Create it.** Ubuntu 24.04 LTS, 1 vCPU, 2 GB. Add your SSH key, and
   turn on monitoring (the agent's memory and disk alerts).
2. **Cloud Firewall** (Networking → Firewalls), attached to the droplet:
   - Inbound: TCP 22 (from your own address if you can), TCP 80, TCP 443 and
     UDP 443.
   - Nothing else. Docker's port publishing goes around `ufw` but not around
     a Cloud Firewall. Every other published port binds to `127.0.0.1`
     anyway (`PUBLISHED_BIND_ADDRESS`).
   - Tailscale traffic arrives on the tunnel, not through this firewall, and
     needs no rule.
3. **SSH.** Keys only: `PasswordAuthentication no` in
   `/etc/ssh/sshd_config.d/`. Turn on `unattended-upgrades`.
4. **Swap, for the host only.** Containers keep `memswap_limit` equal to
   `mem_limit`, so a container that overruns is still killed, visibly.

   ```
   fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
   echo '/swapfile none swap sw 0 0' >> /etc/fstab
   ```
5. **Docker Engine and `make`,** from Docker's apt repository. Clone the
   repository to `/srv/careerpolaris`.
6. **`.env`.** Copy `.env.example` to `.env` and fill it in as below. Then
   `chmod 600 .env`.
7. **Start it.** `careerpolaris_net` exists once `start-infra` has run. Read its
   subnet into `FORWARDED_ALLOW_IPS` before the first `start-app`.

   ```
   make build-infra          # pulls Postgres and Tailscale
   make pull-app RELEASE=release.env   # the release's images, by digest
   make start-infra          # Postgres, then the tunnel forwards 5432 to it
   make start-app            # migrates, then api, web and Caddy
   ```

   Caddy asks Let's Encrypt for `SITE_HOSTNAME`'s certificate on its first
   start. Ports 80 and 443 must already be open.
8. **Backups, nightly,** in root's crontab:

   ```
   15 3 * * * cd /srv/careerpolaris && make backup-db >> /var/log/careerpolaris-backup.log 2>&1
   ```

   Check one now and then without touching the live database:
   - create a scratch database as the superuser;
   - run `make restore-db BACKUP=<key> RESTORE_DB=<scratch>`;
   - drop the scratch database again.

### The droplet's `.env`, beyond the template

| Setting | Value |
|---|---|
| `COMPOSE_PROFILES` | `edge,proxy,tunnel` |
| `APP_ENV` | `production` |
| `SITE_HOSTNAME` | `<droplet-ip>.sslip.io`, until there is a domain |
| `CORS_ALLOWED_ORIGINS`, `WEB_API_BASE_URL`, `OAUTH_REDIRECT_BASE_URL`, `AUTH_PUBLIC_API_BASE_URL` | `https://$SITE_HOSTNAME`, each written out |
| `AUTH_COOKIE_SECURE` | `true` |
| `POSTGRES_HOST` | `postgres` |
| `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL` | `https://<region>.digitaloceanspaces.com` |
| `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | The app's bucket and its key |
| `BACKUP_S3_*` | The backup bucket and its key |
| `TUNNEL_AUTH_KEY`, `TUNNEL_HOSTNAME` | The `tag:careerpolaris-edge` key, `careerpolaris-edge` |
| `GOOGLE_OAUTH_CLIENT_ID` | Blank: Google sign-in waits for a domain of your own |
| `POSTGRES_SHARED_BUFFERS`, `_WORK_MEM`, `_EFFECTIVE_CACHE_SIZE`, `_MAX_CONNECTIONS` | `128MB`, `4MB`, `512MB`, `50` |
| `DB_POOL_SIZE` | `3` |
| `FORWARDED_ALLOW_IPS` | careerpolaris_net's subnet, from `docker network inspect careerpolaris_net` (e.g. `172.18.0.0/16`). Without it every client looks like Caddy, and one sign-up limit covers everyone (ADR 0054). |
| `API_MEM_LIMIT`, `WEB_MEM_LIMIT`, `PROXY_MEM_LIMIT`, `POSTGRES_MEM_LIMIT`, `TUNNEL_MEM_LIMIT` | `512m`, `64m`, `128m`, `512m`, `128m` |
| `API_CPUS`, `POSTGRES_CPUS` | `1.0` each. A ceiling, not a share, and there is one vCPU. |

The GitHub and Jira OAuth apps list `https://$SITE_HOSTNAME/connections/…/callback`
as their callbacks (see `.env.example`).

After a day of use, `make stats` shows each container against its ceiling.
Raise a limit in `.env` if one sits near it or reports `oom_killed=true`.

## 3. The compute machine

1. **Disk encryption on.** This machine holds `MASTER_ENCRYPTION_KEY`, every
   user's connector tokens and a migrator credential. Keep it a machine
   nobody else signs in to.
2. **Docker and `make`,** then clone the repository.
3. **`.env`,** with `chmod 600`:

   | Setting | Value |
   |---|---|
   | `COMPOSE_PROFILES` | `compute,tunnel` |
   | `POSTGRES_HOST` | The droplet's tunnel address, `100.x.y.z` |
   | `POSTGRES_PORT` | `5432` |
   | `DATABASE_URL`, `CRAWLER_DATABASE_URL`, `MIGRATOR_DATABASE_URL` | As on the droplet, with host `100.x.y.z:5432` |
   | `S3_*` | As on the droplet |
   | `TUNNEL_AUTH_KEY`, `TUNNEL_HOSTNAME` | The `tag:careerpolaris-compute` key, `careerpolaris-compute` |
   | `DB_POOL_SIZE` | `3` |
   | Everything else the worker reads | As on the droplet, especially `MASTER_ENCRYPTION_KEY` and the connector secrets |

4. **Start it:**

   ```
   make build-infra          # pulls Tailscale
   make pull-app RELEASE=release.env   # the same release the droplet runs
   make start-infra          # the tunnel, then waits until Postgres answers through it
   make start-app            # migrates (nothing pending: the edge did), then worker and crawler
   ```

The crawler fetches job boards from this machine's address. Its politeness
rules (per-host caps, backing off after a 429 or 403) do not change.

## 4. A release

Copy the run's `release.env` to both machines, next to `.env`.

1. **Edge first.** Run `make pull-app RELEASE=release.env`, then
   `make stop-app`, then `make start-app`. That migrates under the lock.
2. **Then compute,** with the same `release.env`. A compute machine still on the
   previous image refuses to start against the newer schema, and says which
   release to run.

## 5. When something is wrong

- **The SPA says "Processing is offline".** The compute machine is off,
  asleep, or off the tailnet.
  - Run `make stats` there.
  - Run `docker compose -f infra/compose.yml exec tunnel tailscale --socket=/var/run/tailscale/tailscaled.sock status`.
  - Work started meanwhile waits and runs when the machine is back.
- **`start-infra` on compute times out.** The edge is down, or
  `POSTGRES_HOST` is not its tunnel address.
- **Caddy cannot get a certificate.** Ports 80 and 443 are not open in the
  Cloud Firewall, or `SITE_HOSTNAME` does not resolve to the droplet.
- **Disk.** Run `make disk-usage` on the droplet. Old images go with
  `docker image prune`, after a release has settled.
