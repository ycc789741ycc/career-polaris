# 0055. CI releases multi-platform images, which each place pulls by digest

**Status:** Accepted — 2026-10-05.

## Context

The droplet has one vCPU and 2 GB. Installing torch and building the SPA
there would take a very long time, and could run out of memory. The compute
machine runs whatever the edge runs, and an image older than the schema
refuses to start (ADR 0051). So both places must run the same build, and
neither should make it.

The droplet is amd64. The compute machine is the operator's own, likely an
Apple Silicon Mac, so arm64. There, an amd64 image runs under emulation,
which is slow for the embedding model, the crawler's main work.

CI's push trigger named `main` and `develop`. This repository's mainline is
`master`, so CI had never run on a push to it.

## Decision

- **CI runs on every push to `master` and on pull requests.** A push to
  `master` that passes every gate goes on to a `release` job.
- **The release job runs `make push-app`** (`infra/push-release.sh`):
  - it builds the `prod` stage of `jsa-backend`, `jsa-web` and `jsa-proxy`
    for every platform in `RELEASE_PLATFORMS` (default
    `linux/amd64,linux/arm64`), with buildx and QEMU;
  - it pushes them to `RELEASE_REGISTRY` (`ghcr.io/<owner>`), tagged with
    the commit;
  - it writes `release.env`, which names each image by its manifest digest.
  - The file is in the run's summary and its `release-<sha>` artifact.
- **Each place runs `make pull-app RELEASE=release.env`**
  (`infra/pull-release.sh`):
  - it pulls each image by digest and tags it `jsa-*:prod`, which
    `start-app` runs;
  - it refuses a file that names an image without a digest.
  - Compose keeps `pull_policy: never`, so nothing else is ever pulled under
    those names.
- **The order is the edge first, then the compute side,** with the same
  file (`docs/deploy.md`).

## Consequences

Easier:

- One release file pins exactly what both places run. A digest cannot be
  moved the way a tag can.
- The compute machine runs natively on arm64.
- Neither machine needs a build toolchain or the source's dependencies. The
  droplet needs only Docker, `make` and the repository, for the compose files
  and scripts.

Harder:

- **The arm64 images are not what the gates tested.** CI's tests and scans
  ran against the amd64 build. The arm64 one is the same Dockerfile and
  commit, built under emulation, and is checked only by running it.
- **The release job is slow.** Building under QEMU, the proxy's Go build and
  the backend's packages take far longer than native. The job allows 90
  minutes.
- **Private packages need a read-only token** logged in on each machine.
- **The release file has to reach both machines,** copied from the CI run.
  Nothing pushes a release to them.
- **The repository has to be on each machine** for the compose files and
  scripts, at the commit the release was built from.

## Alternatives considered

- **Building on each machine.** That needs no registry, but the droplet
  cannot do it, and two builds of one commit are two artifacts that can
  differ.
- **amd64 only.** It is simpler, and only the gated image ships. But the
  crawler and worker would run emulated on the compute machine, which costs
  most where the work is heaviest.
- **Native arm64 runners and a merged manifest.** It is faster, but it needs
  two build jobs and a merge step, and arm64 hosted runners are not on every
  plan. It is the next step if the emulated build becomes too slow.
- **Releasing by tag.** A git-SHA tag is effectively unique, but tags can be
  overwritten. A digest names the bytes.
- **A deploy job that SSHes into both machines.** The compute machine is
  often off, and is not reachable from CI. Pulling is the operator's step,
  on purpose.
