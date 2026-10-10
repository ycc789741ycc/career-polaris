# 0063. The vulnerability scan blocks a release, and a change only when it touches what is scanned

**Status:** Accepted — 2026-10-10.

## Context

`make scan` runs pip-audit, npm audit and Trivy. Each reads an advisory
database that changes every day, so the same commit can pass on Monday and fail
on Tuesday. The scan was a step in CI's `verify` job, and `verify` gates every
pull request. When an advisory landed against a dependency no open pull request
touched, every one of them went red at once, and none of them could fix it.
They waited for a separate fix to reach master, then for each to be brought up
to date with it (master requires that), then for `verify` to run again.

The scan also read more than ships. pip-audit audited the test image's whole
environment and npm audit every devDependency, so an advisory against pytest,
Vite or ESLint, none of which reach a deployed place, could block a release.

## Decision

- **The scan stays one target.** `make scan` is what runs locally, in CI's
  gates and in the daily scan. It always exits non-zero on a finding; whether
  that blocks is decided by CI (`.github/workflows/scan-gate.sh`).
- **It blocks a version tag.** Nothing is released with a known HIGH or
  CRITICAL finding that has a fix, unless an unexpired exception names it.
- **It blocks a change to what it reads.** A pull request, or a push to
  master, that changes a lockfile, a manifest, a Dockerfile, the proxy, the
  Makefile, an exception file or the scan's own workflow and gate, compared
  with its first parent. Dependabot's pull requests are among them.
- **Otherwise it is advice.** The step runs, and a failure is a warning on the
  run and in its summary, not a red check.
- **A daily scan of master owns new advisories** (`.github/workflows/scan.yml`).
  A failure opens one issue, "Vulnerability scan failing on master", or comments
  on the open one; a clean run closes it.
- **Exceptions are time-boxed.** A finding with a fix nobody can take yet goes
  in `.trivyignore.yaml` (Trivy, with `statement` and `expired_at`) or
  `backend/pip-audit-ignore.txt` (id, expiry date, reason, or the scan fails).
  At most 30 days, renewed on purpose. An expired one blocks again. npm audit
  has no exceptions; a transitive fix is forced with `overrides`.
- **Only what ships is audited.** pip-audit reads the lockfile's runtime set
  (`uv export --no-dev`, hashed) and npm audit runs with `--omit=dev`. Trivy
  still scans the prod images whole.

## Consequences

Easier:

- A new advisory turns one issue red, not every open pull request. Changes
  unrelated to dependencies merge on their own merits.
- A pull request that changes dependencies still cannot bring a known
  vulnerability in, and a release still cannot ship one.
- A finding in a test or build tool no longer blocks a release.
- An exception says why and when it ends, so none outlives its reason
  unnoticed.

Harder:

- **Master can hold a known vulnerability between releases.** An unrelated
  pull request merges past it. The daily issue says so, and the next release is
  blocked until it is fixed or excepted, so the fix cannot be put off for long
  without stopping releases.
- **A finding can be ignored on an advisory run.** A warning is easier to
  overlook than a red check; the issue is the reminder.
- **The list of scanned paths is kept by hand** in `scan-gate.sh`. A new
  Dockerfile, manifest or image pin elsewhere must be added there, or changes
  to it are only advised on.
- **Two exception formats**, because Trivy and pip-audit each read their own.
- **One more workflow, with `issues: write`,** running a full `build-app` every
  day.
- **Advisories against dev tools are no longer reported at all.** A
  compromised build tool is a supply-chain risk the scan never covered well;
  Dependabot still proposes their security updates.

## Alternatives considered

- **Keep the scan blocking on every pull request.** It never lets master hold
  a known finding, but it fails changes for something they did not cause, and
  every open pull request pays for one advisory.
- **Make the scan advisory everywhere and rely on the daily run.** Nothing
  blocks on a pull request, so a dependency change could bring a known,
  fixable vulnerability in and only be caught at the release.
- **Fail only on findings master does not already have** (diffing the scan
  against master's). It is the most exact, but needs a stored baseline per
  scanner and image, compares reports whose formats change with the scanner's
  version, and still fails when the database moves between master's run and
  the pull request's.
- **Freeze the advisory database** (Trivy's `--skip-db-update` against a
  cached copy). It makes runs repeatable by not looking, which is what the scan
  exists to avoid.
- **A separate `scan` job instead of a step in `verify`.** It would show on
  its own line, but it would need the prod images built again in a second job.
