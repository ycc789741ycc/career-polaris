# Deploying CareerPolaris: the droplet and the compute machine

The app runs in two places (ADR 0051):

| Place | Runs | `COMPOSE_PROFILES` |
|---|---|---|
| **Droplet**: DigitalOcean, 1 vCPU, 2 GB | Caddy (ADR 0053), `web`, `api`, Postgres, the tunnel | `serving,proxy,tunnel` |
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
     tagged `tag:careerpolaris-serving` and `tag:careerpolaris-compute`. For a server, turn off key
     expiry on the machines once they join.
   - Restrict the tailnet to what the app needs. In the access policy, allow
     only `tag:careerpolaris-compute` to reach `tag:careerpolaris-serving:5432`:

     ```json
     {
       "tagOwners": {"tag:careerpolaris-serving": ["autogroup:admin"], "tag:careerpolaris-compute": ["autogroup:admin"]},
       "grants": [{"src": ["tag:careerpolaris-compute"], "dst": ["tag:careerpolaris-serving"], "ip": ["tcp:5432"]}]
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
3. **Images.** A version tag (`v1.2.3`) pushed on a commit already on
   `master` is released, once CI's gates pass on it (ADR 0055, 0060).
   - CI builds the prod images for amd64 and arm64 and pushes them to
     `ghcr.io/<owner>/careerpolaris-{backend,web,proxy}:<version>`.
   - The tag's GitHub Release holds `release.env`, which names each image by
     digest.
   - Neither machine builds anything. If the packages are private, give each
     machine a classic token with only `read:packages`, once:
     `docker login ghcr.io -u <user>`.

## 2. The droplet

1. **Create it.** Ubuntu 26.04 LTS (24.04 works too), 1 vCPU, 2 GB. Add your
   SSH key, and turn on monitoring (the agent's memory and disk alerts).
   Under Advanced options → User data, paste `infra/bootstrap-droplet.sh`,
   so the host is prepared (step 4) before anyone can log in.
2. **Reserved IP** (Networking → Reserved IPs), assigned to the droplet. Use
   it, never the droplet's own address, in `SITE_HOSTNAME`: a replacement
   droplet then takes the IP over, and the certificate, every public URL and
   the OAuth callbacks stay as they are. It is free while assigned.
3. **Cloud Firewall** (Networking → Firewalls), attached to the droplet:
   - Inbound: TCP 22 (from your own address if you can), TCP 80, TCP 443 and
     UDP 443.
   - Nothing else. Docker's port publishing goes around `ufw` but not around
     a Cloud Firewall. Every other published port binds to `127.0.0.1`
     anyway (`PUBLISHED_BIND_ADDRESS`).
   - Tailscale traffic arrives on the tunnel, not through this firewall, and
     needs no rule.
4. **The host.** `infra/bootstrap-droplet.sh`, as root, does all of it, and
   running it again changes nothing already in place:
   - SSH by key only. It refuses to run while no `authorized_keys` holds a
     key.
   - Daily security updates (`unattended-upgrades`). It never reboots: when
     `/var/run/reboot-required` exists, reboot at a quiet time.
   - 1 GB of swap, for the host only. Containers keep `memswap_limit` equal
     to `mem_limit`, so a container that overruns is still killed, visibly.
   - Docker Engine and the compose plugin from Docker's apt repository, plus
     `make` and `git`. Docker's repository is not one the automatic updates
     follow: `apt-get upgrade` now and then.

   Pasted as User data, it has run by the time you log in; its output is in
   `/var/log/cloud-init-output.log`. On a droplet created without it, clone
   the repository (next step) and run `infra/bootstrap-droplet.sh`.
5. **The repository,** at `/srv/careerpolaris`:
   `git clone https://github.com/<owner>/career-polaris.git /srv/careerpolaris`.
6. **`.env`,** from the droplet's template, which already holds this
   machine's sizes and every production setting that is not a secret:

   ```
   cp infra/env/droplet-1vcpu-2gb.env.example .env && chmod 600 .env
   ```

   Fill in every blank, as below. `FORWARDED_ALLOW_IPS` waits for the next
   step.
7. **Start it.** `careerpolaris_net` exists once `start-infra` has run. Read its
   subnet into `FORWARDED_ALLOW_IPS`, then check `.env` against its template,
   before the first `start-app`.

   ```
   make build-infra          # pulls Postgres and Tailscale
   make pull-app RELEASE=release.env   # the release's images, by digest
   make start-infra          # Postgres, then the tunnel forwards 5432 to it
   docker network inspect careerpolaris_net -f '{{(index .IPAM.Config 0).Subnet}}'
   make check-env TEMPLATE=infra/env/droplet-1vcpu-2gb.env.example
   make start-app            # migrates, then api, web and Caddy
   ```

   `check-env` fails on a setting `.env` lacks or leaves blank, and lists
   the values that differ from the template. It prints no secret.

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

### The droplet's `.env`: what the template leaves blank

The template (`infra/env/droplet-1vcpu-2gb.env.example`) sets the profiles,
`APP_ENV`, the secure cookie, the Postgres host and the sizes: each
container's memory and CPU ceiling (no CPU above 1.0, since there is one
vCPU), Postgres's own memory settings and `DB_POOL_SIZE`. What it leaves blank
is this machine's alone:

| Setting | Value |
|---|---|
| `SITE_HOSTNAME` | `<reserved-ip>.sslip.io`, until there is a domain |
| `CORS_ALLOWED_ORIGINS`, `WEB_API_BASE_URL`, `OAUTH_REDIRECT_BASE_URL`, `AUTH_PUBLIC_API_BASE_URL` | `https://$SITE_HOSTNAME`, each written out |
| `POSTGRES_SUPERUSER_PASSWORD`, `APP_RW_PASSWORD`, `CRAWLER_RW_PASSWORD`, `AGGREGATOR_PASSWORD`, `MIGRATOR_PASSWORD`, `AUTH_JWT_SECRET` | Each its own `openssl rand -hex 32` |
| `DATABASE_URL`, `CRAWLER_DATABASE_URL`, `MIGRATOR_DATABASE_URL` | `postgresql+asyncpg://app_rw:<pw>@postgres:5432/careerpolaris`, the same for `crawler_rw`, and `postgresql+psycopg://migrator:<pw>@postgres:5432/careerpolaris`: the shapes `.github/workflows/ci-env.sh` writes |
| `MASTER_ENCRYPTION_KEY` | `openssl rand -base64 32`, the same on the compute machine. Keep a copy off the droplet: without it every stored connector token and AI key is unreadable. |
| `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL` | `https://<region>.digitaloceanspaces.com` |
| `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | The app's bucket and its key |
| `BACKUP_S3_*` | The backup bucket and its key |
| `TUNNEL_AUTH_KEY` | The `tag:careerpolaris-serving` key |
| `GITHUB_OAUTH_*`, `JIRA_OAUTH_CLIENT_*` | From the OAuth apps |
| `FORWARDED_ALLOW_IPS` | careerpolaris_net's subnet (step 7, e.g. `172.18.0.0/16`). Without it every client looks like Caddy, and one sign-up limit covers everyone (ADR 0054); `check-env` refuses it blank. |

`GOOGLE_OAUTH_*` and `RELEASE_REGISTRY` stay blank: Google sign-in waits for a
domain of your own, and the droplet pushes no images.

The GitHub and Jira OAuth apps list `https://$SITE_HOSTNAME/connections/…/callback`
as their callbacks (see `.env.example`).

After a day of use, `make stats` shows each container against its ceiling.
If one sits near it or reports `oom_killed=true`, raise its limit in the
template, by pull request, and then in `.env`; `check-env` lists any value
the two disagree on.

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
   | `JIRA_REPORTING_OWNER_ID` | Blank at first; see step 5 (ADR 0061) |
   | Everything else the worker reads | As on the droplet, especially `MASTER_ENCRYPTION_KEY` and the connector secrets |

4. **Start it:**

   ```
   make build-infra          # pulls Tailscale
   make pull-app RELEASE=release.env   # the same release the droplet runs
   make start-infra          # the tunnel, then waits until Postgres answers through it
   make start-app            # migrates (nothing pending: the edge did), then worker and crawler
   ```

5. **Turn on Atlassian's personal data report** (ADR 0061), once, after the
   first release is up. Every Jira connection is reported weekly with your
   own Jira token; until this is done the worker logs `account_report.off`
   daily and reports nothing.

   1. Sign up at `https://$SITE_HOSTNAME` and connect Jira with the Atlassian
      account that owns the OAuth app.
   2. Find your account id: it is the `id` in the reply to `GET /api/v1/me`,
      which the SPA sends on sign-in (the browser's developer tools, Network
      tab).
   3. Put it in this machine's `.env` as `JIRA_REPORTING_OWNER_ID`, then
      `make stop-app && make start-app`.

   Keep that Jira connection: disconnecting it, deleting the account, or
   leaving it unused until Atlassian expires its refresh token stops every
   report (`account_report.no_reporting_connection` or
   `account_report.failed` in the worker's log) until you reconnect.

The crawler fetches job boards from this machine's address. Its politeness
rules (per-host caps, backing off after a 429 or 403) do not change.

## 4. A release

Tag `origin/master` with the next version and push the tag:

```
make release BUMP=patch   # or minor, or major
```

SemVer: raise the patch for fixes, the minor for features, the major when a
place needs more than a pull. It shows the version and the commit and asks
first (`YES=1` does not). Running it again is safe: it does nothing once
`origin/master` is released, and pushes a tag an earlier run left unpushed. By
hand it is `git fetch origin`, `git tag -a v0.1.0 origin/master -m v0.1.0`,
`git push origin v0.1.0`. When CI is green, download `release.env` from
the GitHub Release (`gh release download v0.1.0 -p release.env`) and copy it
to both machines, next to `.env`.

1. **Edge first.** Run `git pull`, `make pull-app RELEASE=release.env`, then
   `make check-env TEMPLATE=infra/env/droplet-1vcpu-2gb.env.example`: a
   release that added a setting fails here, naming it, rather than at start.
   Then `make stop-app` and `make start-app`, which migrates under the lock.
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
