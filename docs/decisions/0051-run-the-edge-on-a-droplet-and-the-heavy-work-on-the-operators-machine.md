# 0051. The edge runs on a droplet, the heavy work on the operator's machine

**Status:** Accepted — 2026-10-05.

## Context

The app is going to run on a DigitalOcean droplet with one vCPU and 2 GB of
memory. As it stands it does not fit there:

- The worker and the crawler each load the local embedding model, which costs
  about 1 GiB in each process.
- A PDF render spikes on top of that.
- Postgres and MinIO had 1 GB ceilings each.

The operator has a machine with memory to spare, but it is not always on and
sits behind a home router. The api, the SPA and Postgres are light. They have
to be always on, because they are what a user's browser talks to.

`architecture.md` left the platform open (open question 1).

## Decision

One image and one pair of compose files run in two places. Each place's
`.env` chooses its part with `COMPOSE_PROFILES`.

- **The edge (the droplet):** `edge` and `tunnel`. That is `api`, `web`,
  Postgres and the tunnel. Postgres sits beside the api because every request
  reads it.
- **The compute side (the operator's machine):** `compute` and `tunnel`. That
  is `worker` and `crawler`, which hold the embedding model, run the renders
  and do the syncs.
- **Development and CI:** `edge,compute,local`, so everything runs on one
  machine with MinIO and no tunnel. A deployment stores files in a Spaces
  bucket that both places reach.
- **The tunnel** is Tailscale, in a container on the host's network. The
  compute side dials out, so it opens no inbound port. On the edge,
  `infra/tunnel-up.sh` forwards only the tunnel's port 5432 to Postgres on
  loopback. On the compute side, it waits until Postgres answers across the
  tunnel before anything migrates. The database URLs there name the edge's
  tunnel address.
- **Published ports bind to `PUBLISHED_BIND_ADDRESS`, default `127.0.0.1`.**
  Docker writes its own iptables rules ahead of `ufw`. Before this change,
  `0.0.0.0` published the api over plain HTTP, and Postgres and MinIO too, on
  any host with a public address.
- **Both places migrate when they start, under a Postgres advisory lock**
  (`cli.migrate.migration_lock`). A place starting at the same moment waits,
  then finds nothing pending.
- **An image older than the schema refuses to start.** If the database is at
  a revision that image's migrations do not contain, migration stops with
  `SchemaAheadError`, and the app is not started on code that predates its
  tables.
- **What `make` covers in each place.**
  - `build-app`, `stop-app`, `stop-infra`, `logs` and `stats` act on every
    profile.
  - `build-infra`, `start-infra` and `start-app` act on this place's.
  - A `COMPOSE_PROFILES` that selects nothing fails with what to set.
  - `bootstrap-roles.sh` and `disk-usage.sh` act only where Postgres runs.
- **Infra restarts with its host** (`restart: unless-stopped`).
- **Postgres's memory settings are `POSTGRES_*` settings,** defaulting to
  Postgres's own.

## Consequences

Easier:

- The droplet carries about 1 GB. The heavy processes run where memory is
  cheap, with no change to their code.
- No managed database or object store bill beyond Spaces, and no platform to
  learn.
- A queued job survives the compute side being away. It runs when the
  machine is back, because the queue and the outbox are in Postgres on the
  edge.

Harder:

- **Background work is only up while the operator's machine is.** That
  covers analyses, builds, Advisor drafts, PDF exports, syncs and crawling. A
  later step has to tell the user so, instead of reporting the work as lost.
- **Two `.env` files to keep.** The names are the same and the values differ,
  and the compute side's database URLs go through the tunnel.
- **The tunnel is a dependency.** If Tailscale is down, the compute side is
  down. Its auth key is one more secret.
- **The trust boundary includes the operator's machine.** It holds
  `MASTER_ENCRYPTION_KEY`, connector tokens and a DDL-capable
  `MIGRATOR_DATABASE_URL`. It needs disk encryption and no other users.
- **Latency.** Every query the worker makes crosses the tunnel. That is fine
  for jobs that wait on an LLM. A role-map build makes many small queries, so
  measure it before trusting it.
- **The crawler fetches from the operator's home address.**
- **The droplet carries torch.** The api image includes it, about 2 GB of
  disk, because the phase keeps one artifact.
- **Existing `.env` files need `COMPOSE_PROFILES`.** Without it, `start-app`
  fails with what to set.

## Alternatives considered

- **Everything on the droplet.** Lost on memory: two copies of the embedding
  model alone exceed it.
- **Everything on the droplet, with embeddings moved to ONNX Runtime.** It
  would fit, with about 1.4–1.7 GB at peak. That leaves no headroom when a
  render and a crawl coincide, and it changes how every stored vector is
  made. Kept as an option should the operator's machine go away.
- **Managed Postgres and Spaces, with the app on the droplet.** Cleaner for
  availability, but it costs about $20 a month more, and the embedding
  processes still did not fit beside the api.
- **A make variable per place (`SITE=edge`).** It would duplicate what compose
  profiles already do, and every target would need to pass it. A profile set
  in `.env` changes nothing about how a target is called.
- **Publishing Postgres on the tunnel's address instead of forwarding to
  loopback.** At boot, Docker would have to bind an address the tunnel had
  not brought up yet, and a bind failure does not retry. `tailscale serve`
  forwards to loopback whenever both are up.
- **WireGuard by hand.** No coordination service, but keys, peers and NAT
  traversal to manage. Tailscale does that and fits in one container.
