# 0056. Everything inside is renamed to CareerPolaris

**Status:** Accepted — 2026-10-05. Amended by [0059](0059-rename-the-repository-to-career-polaris.md).

## Context

Phase 11 renamed the app to CareerPolaris and kept every internal name. The
images, network and compose projects still said `jsa-*`, `jsa_net`,
`jsa-infra` and `jsa-app`. The service name, token issuer and audience, and
package names still said `job-searching-advisor`, and the crawler's user agent
`JobSearchingAdvisorBot`. The reason given was that renaming would break every
running stack, for no change a user sees.

The app has not been deployed yet (Phase 12). Renaming now costs one
development machine a data copy. After the droplet is live, it would cost a
production migration as well. The old names also keep leaking into new
work: Phase 12 added `jsa-proxy`, `JSA_*_IMAGE` and Tailscale tags named
after them.

## Decision

Every name inside the code base becomes CareerPolaris's, and `jsa` is not
used for anything new.

| What | Was | Is |
|---|---|---|
| Images | `jsa-{backend,web,proxy}` | `careerpolaris-{backend,web,proxy}` |
| Network | `jsa_net` | `careerpolaris_net` |
| Compose projects | `jsa-infra`, `jsa-app` | `careerpolaris-infra`, `careerpolaris-app` |
| Cookies | `jsa_refresh`, `jsa_google_attempt` | `careerpolaris_refresh`, `careerpolaris_google_attempt` |
| `SERVICE_NAME`, token issuer, audience | `job-searching-advisor`, `…-api` | `careerpolaris`, `careerpolaris-api` |
| Crawler user agent | `JobSearchingAdvisorBot/1.0` | `CareerPolarisBot/1.0` |
| Packages | `job-searching-advisor-{backend,web}` | `careerpolaris-{backend,web}` |
| Release file | `JSA_*_IMAGE` | `CAREERPOLARIS_*_IMAGE` |
| Font directory, CI database and bucket, Tailscale tags | `jsa` | `careerpolaris` |

- **Existing data comes across once, by copy, by hand.** The repository
  carries no command for a job each machine does once.
  - Stop the old stack first, so Postgres is not copied mid-write. Then copy
    each old volume into its new name, preserving ownership, and keep the old
    ones.
  - Each new volume carries the labels compose would give it, so the new
    project adopts it:

  ```sh
  docker compose -p jsa-app down
  docker compose -p jsa-infra stop
  for pair in jsa-infra_pgdata:careerpolaris-infra_pgdata \
              jsa-infra_objectdata:careerpolaris-infra_objectdata \
              jsa-app_modelcache:careerpolaris-app_modelcache; do
    old=${pair%%:*}; new=${pair#*:}; project=${new%%_*}; volume=${new#*_}
    docker volume create --label com.docker.compose.project=$project \
      --label com.docker.compose.volume=$volume "$new"
    docker run --rm --network none -v "$old:/from:ro" -v "$new:/to" \
      alpine:3.24.2 sh -c 'cp -a /from/. /to/'
  done
  ```
- **The Git repository keeps its name,** `job-searching-advisor`. Renaming it
  belongs to GitHub, and every clone's remote, not to this code base.
- **History keeps the names it was written with:** accepted ADRs, past
  phases in `docs/plan.md`, and the excalidraw drawings.
- **A `.env` keeps its values.** A database named `jsa`, or a bucket
  `jsa-local`, is the operator's configuration. It still works, and changing
  it is a data move of its own.

## Consequences

Easier:

- One name everywhere a person reads it: `docker ps`, logs, the robots.txt
  rules a board writes for us, and the release.
- The droplet starts life on the final names, with no production rename
  ever to do.

Harder:

- **Every running development stack needs one manual step:** stop it, copy
  its volumes as above, then start. Until then, a new
  `start-infra` starts an empty database.
- **The old volumes, images, network and stopped containers stay behind**
  until the operator removes them.
- **Everyone is signed out once.** The refresh cookie has a new name, and
  tokens carry a new issuer and audience.
- **A board's robots.txt rules aimed at `JobSearchingAdvisorBot` no longer
  apply to us.** The same `*` rules still do.
- **Every image is rebuilt under its new tag** (`make build-app`, both
  modes).

## Alternatives considered

- **Keep the old internal names** (Phase 11's choice). It is free today, but
  the cost only grows once the droplet runs. The names also kept spreading
  into new code.
- **Pin the volumes' names to the old ones** (`name: jsa-infra_pgdata`).
  No copy would be needed, but `jsa` would live on in the compose files
  forever, which is what this decision removes.
- **Rename the volumes with a move instead of a copy.** Docker has no rename,
  so a move is a copy and a delete. Keeping the old volumes until the
  operator has seen the new stack run costs disk space, not risk.
