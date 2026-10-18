# 0081. Roll out each release CI publishes from the compute machine

**Status:** Accepted — 2026-10-18. Amends [0055](0055-release-multi-platform-images-by-digest-from-ci.md) and [0060](0060-release-only-a-version-tag-on-master.md).

## Context

A release ends with CI (ADR 0055, 0060): `make release` tags `origin/master`,
the `release` job runs the gates on the tag, pushes the prod images and
attaches `release.env` to the tag's GitHub Release. Deploying it was by hand:
download the file, then on the droplet `pull-app`, `check-env`, `stop-app`,
`start-app`, then the same on the compute machine (`docs/deploy.md`,
section 4).

Doing that by hand had two costs beyond the time. It was easy to skip the
compute machine or do it hours later, and while it waited its old worker went
on writing into the schema the droplet had just migrated. And nothing stopped
the worker while the droplet migrated, so a migration that rewrote rows could
race a job writing the old shape.

The two machines are not alike. The droplet is always on. The compute machine
is the operator's Mac: it dials out through the tunnel, opens no port, and
sleeps. Both reach the same Postgres.

## Decision

- **The release marked Latest is what production runs.** The `release` job
  publishes the GitHub Release as its last step, after every gate and image
  push, with `--latest`, and `release.env` now starts with
  `RELEASE_VERSION=vX.Y.Z`. A Latest release with that file therefore means CI
  finished it. `make release` only makes plain versions (`push-app` refuses
  any other tag), so there are no pre-releases to skip.
- **One controller, on the compute machine.** A launchd agent there runs
  `make roll-out` every five minutes and on wake. It downloads the Latest
  release's `release.env` (public, no token), and when a machine runs another
  version it rolls the release out to both, in order:
  1. prepare both machines while everything still runs: check out the tag,
     pull the images by digest, `check-env`, and check the schema is one the
     new images know;
  2. stop the compute machine's app, the worker draining its running jobs;
  3. on the droplet, over SSH, `stop-app` and `start-app`, which migrates
     with no writer left, then wait until it is healthy;
  4. start the compute machine on the new release.
- **The droplet decides nothing.** It runs no timer; it runs the steps it is
  given, detached from the SSH session so a dropped connection does not cut a
  migration off.
- **SSH over the existing tunnel.** The Mac's own OpenSSH client reaches the
  droplet's `sshd` through the tunnel container (`tailscale nc` as its proxy
  command), as a `deploy` user with a key of its own. The tailnet grant adds
  `tcp:22` from `tag:careerpolaris-compute` to `tag:careerpolaris-serving`.
- **Rolling back is `make rollback-release TAG=`**, which marks an earlier
  release Latest. The controller then rolls both machines back to it, the
  same way.

## Consequences

Easier:

- A release reaches both machines within minutes of CI finishing, with nobody
  logged in to either.
- Nothing writes while the schema changes, and an old worker never runs
  against a new schema: the compute machine stays stopped from before the
  migration until it runs the new release.
- A release that cannot run (a missing setting, a schema the images do not
  know) stops before anything is stopped, on either machine.
- Rolling back is one command, and the same path as rolling forward.

Harder:

- **`make release` now ships.** There is no second look between the gates and
  the machines.
- **What production runs is set outside git,** by which GitHub Release is
  Latest. The record of what ran when is the Releases page and the rollout's
  log and reports, not commit history.
- **Nothing deploys while the compute machine is off or asleep,** the droplet
  included: deploying the droplet alone would leave an old worker to wake
  into a new schema.
- **The compute machine can change the droplet.** `deploy` is in the
  droplet's `docker` group, which is root there in effect; the tailnet grant
  limits who reaches its `sshd` to the compute machine's tag.
- **Every release stops all background work,** not only the api, until the
  compute machine starts again, and a long job delays the rollout by up to the
  worker's drain period while it finishes.
- **The controller runs on the host,** under launchd, outside a container: it
  stops and starts the stack and checks out the code that defines it, so it
  must outlive both. One more thing to install and keep running.
- **A rollback past a migration does not work:** the older image refuses the
  newer schema. The controller says so before stopping anything, and such a
  release is fixed forward.

## Alternatives considered

- **A reconciler on each machine, coordinated through Postgres.** Each machine
  pulls on its own timer; the droplet sets a maintenance flag, the worker and
  crawler pause themselves, and every write takes a shared lock on the
  migration version row. It needs no SSH and the droplet deploys while the Mac
  is off, but it spreads one ordered rollout across two timers, a flag table
  and a lock in every write, for two machines one script can drive in order.
- **A promotion pull request** writing the release into a file on `master`,
  merged to deploy and reverted to roll back. It records every deploy in git,
  but adds a merge after `make release` has already decided, and needs a
  GitHub App token: a pull request opened with `GITHUB_TOKEN` runs no checks,
  so it never auto-merges.
- **Push from CI over Tailscale and SSH.** CI would hold a tailnet key and a
  key to production, and a push to a sleeping Mac fails.
- **A self-hosted GitHub runner on the Mac.** The repository is public, so a
  workflow that reaches that runner runs on the machine holding production's
  `.env` and the tunnel to Postgres. Labels, environments and approval of
  outside contributors can fence it, but only while every one of those
  settings stays right.
- **Argo CD or Flux.** They reconcile Kubernetes. A cluster would take most of
  the droplet's memory and stretch over a laptop that sleeps.
- **Doco-CD, Komodo, Portainer or Kamal.** They deploy by running compose or
  containers their own way, around `migrate` before start, `check-env`, the
  stack-owner checks and the digests in `release.env`, and none knows this
  order: drain the compute machine, migrate on the droplet, then start it.
