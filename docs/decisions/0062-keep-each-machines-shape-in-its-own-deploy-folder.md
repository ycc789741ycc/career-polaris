# 0062. Each machine's shape lives in its own folder in deploy/, and .env holds only what the app reads

**Status:** Accepted — 2026-10-09. Supersedes [0057](0057-call-the-api-web-and-postgres-profile-serving.md); amends [0051](0051-run-the-edge-on-a-droplet-and-the-heavy-work-on-the-operators-machine.md).

## Context

ADR 0051 put the droplet and the compute machine on one set of compose files,
choosing what runs in a place with `COMPOSE_PROFILES` in its `.env`. Every size
a place needed went into `.env` too, as optional settings the compose files
read: `*_MEM_LIMIT` and `*_CPUS` for each service, `DOCKER_LOG_*`, Postgres's
`shared_buffers`, `work_mem`, `effective_cache_size` and `max_connections`,
the published ports and their bind address. The droplet's values were a
template, `infra/env/droplet-1vcpu-2gb.env.example`, copied by hand.

Two problems came of it.

- **`.env` mixed two kinds of value.** What the application reads — secrets,
  hosts, URLs, its own knobs — really does change per environment. The size
  of a container, which services run and Postgres's memory follow the
  machine's spec instead. They lived in an unversioned file on each box,
  where a limit raised by hand left no trace, and drifted from the template
  without anyone seeing.
- **Two stacks could not share a host.** The compose project names
  (`careerpolaris-app`, `careerpolaris-infra`) and the network
  (`careerpolaris_net`) were fixed. The operator's Mac is the compute machine
  and also where development happens: a development `make start-app` there
  would have recreated the production worker and crawler as development ones,
  and a `make stop-infra` would have taken the tunnel down.

## Decision

- **The boundary.** A value the application process reads, or any secret or
  hostname, is in `.env`. A value only Docker or an infra server reads, and
  that is not secret, is a literal in the machine's compose files: which
  services run, memory, CPU and process ceilings, log rotation, Postgres's
  sizing, published ports and their bind address, the image stage, and the
  project and network names. `make lint` fails if `.env.example` declares one
  of the latter again.
- **One folder per machine spec**, each with two files, the app's and the
  infra's, as two compose projects as before:

  ```
  deploy/compose.app.base.yaml     the app's services: image, command, config from .env, hardening
  deploy/compose.infra.base.yaml   postgres, objectstore, tunnel; same
  deploy/<machine>/compose.app.yaml
  deploy/<machine>/compose.infra.yaml
  ```

  A machine's file picks the services it runs with `extends` from a base and
  adds what depends on the machine. The machines are `local` (a developer's
  laptop), `ci` (CI's runner), `droplet-1vcpu-2gb` and `compute-m5pro-48gb`.
  `compose.yaml`, `compose.dev.yaml`, `infra/compose.yml`, `infra/env/` and
  every profile are gone; the scripts that lived in `infra/` are in `scripts/`.
- **A checkout names its machine in `.machine`**: one line, git-ignored, with
  `.machine.example` saying `local`. Every target that touches containers
  reads it and fails, saying what to write, while it is missing.
- **The machine decides the image; `MODE` is gone.** `local` runs the `dev`
  stage with the source mounted and reloading, as `MODE=dev` did; every other
  machine runs `prod`, nothing mounted. Passing `MODE=` fails with a pointer
  here. `format` and `lock` always use `local`'s file, where the mounts live.
- **Names keep stacks apart.** The droplet and the compute machine keep the
  names they had (`careerpolaris-app`, `careerpolaris-infra`,
  `careerpolaris_net`), so their volumes — Postgres's data, the proxy's
  certificates, the Tailscale identity, the downloaded model — carry over
  untouched. `local` and `ci` end theirs in `-local` and `-ci`, and `ci`
  publishes 21474–21477 beside `local`'s 21470–21473. A development clone on
  the compute machine therefore runs beside production without touching it.
- **A stack belongs to the checkout that started it.** Every target that
  starts, stops or replaces containers or data first refuses a project whose
  containers another checkout started (compose's
  `com.docker.compose.project.working_dir` label), naming that checkout.

## Consequences

Easier:

- `.env` says only what the application is told. Diffing two places' `.env`
  shows real configuration differences, not container sizes.
- A machine's shape is reviewed: a ceiling raised, a service added or
  Postgres resized is a pull request with a reason, and `git log` shows when.
- Development and production compute run side by side on the operator's Mac,
  and a clone pointed at the other's machine is refused rather than obeyed.
- What runs where is read in one file, not worked out from profiles.

Harder:

- **Changing a limit on a box is a pull request**, then a pull there. There is
  no quick edit of `.env` to buy headroom during an incident; editing the
  machine's file in place works, but leaves the checkout dirty until the
  change is merged.
- **A new machine is a new folder.** Two machines of the same spec share one;
  a machine of a new spec needs its own, even for a one-off.
- **A laptop runs only the `dev` images.** Running the prod images locally
  means a second clone whose `.machine` says `ci`, and `make scan`, which
  covers the prod images, runs only there (as CI does).
- **This deviates from the design guideline** in three places, which this
  record accepts: ceilings and Postgres's sizing are literals in compose
  files rather than `.env` settings; `build-app`, `start-app` and `stop-app`
  take no `MODE`; and there is no root `compose.yaml` with a
  `compose.dev.yaml` overlay.
- **Existing development data does not follow.** A laptop's Postgres and
  object storage were in `careerpolaris-infra_pgdata` and
  `careerpolaris-infra_objectfiles`; `local` uses `careerpolaris-infra-local_*`.
  To keep them, copy each once, with both stacks stopped:

  ```
  docker volume create careerpolaris-infra-local_pgdata
  docker run --rm -v careerpolaris-infra_pgdata:/from:ro -v careerpolaris-infra-local_pgdata:/to \
    alpine:3.22 sh -c 'cp -a /from/. /to/'
  ```

  and likewise for `objectfiles` and the app's `modelcache`. The repo carries
  no command for it. Do not do this on the compute machine, where
  `careerpolaris-infra_*` is production's.
- **Each deployed place deletes the moved settings from its `.env` once.**
  Left there they are ignored; `make check-env` lists them as extras.
- `extends` repeats a few lines per machine (each service it runs, with its
  ceilings), which is the price of reading a machine's shape in one place.
- The tunnel still joins the host's network, so on the compute machine a
  development container whose `.env` named the droplet's tunnel address
  could reach production Postgres. Separate names do not prevent that; the
  development `.env` does.

## Alternatives considered

- **Keep everything in `.env`, with per-machine templates** (ADR 0051 as it
  was). Lost: it is the mixing this fixes, and it never let two stacks share
  a host.
- **Suffix the names by `MODE`** (`careerpolaris-app-dev`), leaving profiles
  and sizes in `.env`. Lost: it fixes the shared host and nothing else, and it
  would have had infra targets take `MODE` too.
- **Name the machine in `.env`** (`DEPLOY_MACHINE=`). Lost: it breaks the
  boundary in the one place everyone looks.
- **Name it with a make argument** (`make start-app MACHINE=…`). Lost: typed on
  every command on a deployed box, and forgetting it on the droplet would start
  the `local` stack — Postgres and the S3 gateway — on 2 GB.
- **One self-contained file per machine, no bases.** Lost: every image pin,
  command and hardening line copied four times, and Dependabot bumping each.
- **Profiles inside per-machine files.** Lost: a profile is a second way of
  saying what runs, and what runs is exactly what a machine's file is for.
