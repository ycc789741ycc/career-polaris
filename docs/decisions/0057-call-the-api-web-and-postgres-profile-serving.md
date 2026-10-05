# 0057. The profile with the api, the SPA and Postgres is called `serving`

**Status:** Accepted — 2026-10-05.

## Context

ADR 0051 split the services into compose profiles and called the always-on
part `edge`: `api`, `web` and Postgres. The name came from the place, the
droplet facing users, not from what the services do. It reads wrong in both
usual senses of the word:

- **The network edge.** That is the layer that first meets internet traffic.
  Here that layer is Caddy, in the `proxy` profile.
- **Edge computing.** That is light work done close to the user. The droplet
  holds the database and does most of the serving.

## Decision

The profile is renamed from `edge` to `serving`: the services that answer
requests and must always be on. Every other profile keeps its name.

| Place | `COMPOSE_PROFILES` |
|---|---|
| Droplet | `serving,proxy,tunnel` |
| Compute machine | `compute,tunnel` |
| Development and CI | `serving,compute,local` |

The docs call the places "the droplet" and "the compute machine". "Edge"
stays only where it means Caddy's place at the network boundary.

## Consequences

Easier:

- **The name says what the profile starts,** and no longer collides with
  Caddy's role.

Harder:

- **Every `.env` with `edge` in `COMPOSE_PROFILES` must change.** Compose
  ignores a profile name it does not know, so the old line would quietly
  start the other services alone. The Makefile therefore refuses any name no
  service is in (`require-known-profiles`), and says that `edge` is now
  `serving`. No deployed place uses it yet.
- **ADR 0051 and the Phase 12 plan still say `edge`.** They keep the name
  they were written with.

## Alternatives considered

- **`core`.** Short, but it says nothing about the services being always on,
  or about why they live on the droplet.
- **Naming every profile after a place** (`cloud`, `home`, `dev`). Simpler to
  pick, but the roles could no longer be recombined, and it is a larger
  change than the one name that misled.
