# 0082. Pull release images anonymously, and time out every rollout step

**Status:** Accepted — 2026-11-21. Amends [0081](0081-roll-out-each-release-from-the-compute-machine.md).

## Context

v0.3.3 was published at 17:10 UTC on 2026-11-20. The rollout started at 17:15
and the droplet was prepared by 17:17, but the compute machine's `prepare`
finished at 00:10 the next day: seven hours, with the droplet's api and both
machines' old release running throughout and nothing reported.

The step was stuck in its first `docker pull`. Docker Desktop's log shows no
pull request between 17:17 and 00:09:34, so the CLI was blocked before it
reached the engine. Before the engine, `docker pull` asks the configured
credential helper (`credsStore: desktop`, which reads the macOS Keychain) for
the registry's login. The Mac never slept, but its display was off from
00:48 to 08:09:30 local time; the pull went through four seconds after the
operator came back to it. A Keychain read from a launchd agent can wait for
someone at the screen. That hold was the inference; the logs could not show
the prompt itself.

Two things made a wait into an outage. The pull asked for credentials it did
not need: the `careerpolaris-*` packages on ghcr.io are public, and an
anonymous token pulls them. And `ROLLOUT_STEP_TIMEOUT_SECONDS` bounded only a
step run over SSH; a step on the controller's own machine ran with no deadline,
so the pass could wait forever without failing, retrying or reporting.

## Decision

- **Release pulls are anonymous.** `pull-release.sh` pulls each image with a
  `DOCKER_CONFIG` of its own holding `{}`, so no credential helper and no
  stored login takes part. It keeps the endpoint the machine's own config
  chooses by passing it as `DOCKER_HOST` (from `docker context inspect`,
  unless `DOCKER_HOST` is already set): on the Mac that is Docker Desktop's
  socket. This holds on every machine, not only the controller, so a pull is
  the same everywhere.
- **The release images stay public.** That is now a requirement of the
  release path, not a setting of the packages.
- **Every rollout step has the deadline.** A local step runs in a process
  group of its own and is stopped (TERM, then KILL five seconds on) once it
  outlives `ROLLOUT_STEP_TIMEOUT_SECONDS`, then fails like a remote step that
  ran too long: recorded in `.rollout/failed`, reported, and retried after
  `ROLLOUT_RETRY_SECONDS`.

## Consequences

Easier:

- A rollout no longer depends on anyone being at the Mac, nor on the
  Keychain being readable from launchd.
- A step that hangs for any reason fails within the deadline, and the
  existing retry and GitHub failure report take over.
- A machine needs no `docker login` for releases.

Harder:

- **Making the packages private breaks every deploy,** at the pull, until a
  credentialed path is built. That would need a credential the controller can
  read without a session (a file-backed config with a read-only token), which
  this decision deliberately leaves out.
- **A legitimately slow local step is now cut off.** The compute machine's
  `stop-app` waits up to the worker's drain (`WORKER_DRAIN_SECONDS`, 840) and
  its 15-minute grace; the deadline (3600 s) must stay above every step's
  longest honest run, or a rollout fails that would have finished.
- A step stopped mid-way leaves what it had done: `prepare` is idempotent and
  stops nothing, but a stopped local `start-app` leaves the writers stopped, as
  any failure after the stop does under ADR 0081.

## Alternatives considered

- **A read-only token in a file-backed Docker config for the controller.** It
  keeps the packages free to go private, but it puts a long-lived credential on
  disk to grant access nobody needs today, and adds its own rotation. Lost to
  the anonymous pull, which needs no secret.
- **Turn off the Keychain prompt** (granting the helper "Always Allow", or
  keeping the screen unlocked). It depends on settings outside the repo that
  the next Docker Desktop update can reset, and still leaves any other hang
  without a deadline. Lost.
- **The deadline alone.** It turns the seven-hour wait into a failed pass, but
  every retry would wait on the same prompt while nobody is at the Mac, so
  releases would still deploy only when someone is there. Kept as half of the
  decision, not all of it.
