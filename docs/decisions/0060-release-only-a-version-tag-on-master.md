# 0060. CI releases only a version tag on a commit already on master

**Status:** Accepted — 2026-10-06. Amends [0055](0055-release-multi-platform-images-by-digest-from-ci.md).

## Context

ADR 0055 released every push to `master` that passed the gates. Each merge
therefore ran the release job: the prod images for amd64 and arm64, the latter
under QEMU, in a job that allows 90 minutes, pushed to GHCR. Deploying stays
the operator's step (`make pull-app RELEASE=release.env` on each machine), so
most of those releases were never pulled. They cost CI time and registry
space, and named themselves only by a commit SHA.

There was also no point to cut a hotfix from. The design guideline cuts a
hotfix "from the existing released version it fixes — that release's branch or
tag". The repository had no tags; a release lived only in a CI run's artifact,
which expires.

## Decision

- **A release is a version tag.** `vMAJOR.MINOR.PATCH`, SemVer, starting at
  `v0.x` while the product is pre-1.0. Pushing one is what releases.
- **CI still runs the gates on every pull request and every push to
  `master`.** It also runs them on a pushed `v*` tag, and only then goes on
  to the `release` job, so the images shipped are built from a commit whose
  gates passed in the same run.
- **The tag must be on `master`.** `infra/push-release.sh` refuses unless
  `HEAD` carries a tag of that exact shape and is an ancestor of
  `origin/master`. The check lives in the script, not the workflow, so
  `make push-app` refuses the same way anywhere.
- **Images are tagged with the version** instead of the commit.
  `release.env` still names each by digest, and `pull-app` still pulls by
  digest: the version is for people, the digest is what runs (0055 stands).
- **`release.env` is attached to the tag's GitHub Release**, created by the
  job with generated notes, in place of a run artifact.

The rest of 0055 — multi-platform images, buildx under QEMU, pulling by
digest, edge first — is unchanged.

## Consequences

Easier:

- A merge costs only the gates; the slow multi-platform build runs when
  something is meant to ship.
- A deployed place runs a named version, and the tag marks the exact commit,
  so a hotfix has a release to branch from.
- `release.env` stays downloadable as long as the release exists.

Harder:

- **Shipping is a deliberate step.** Merged work waits on `master` until
  someone tags it, and the operator chooses the version number.
- **The gates run twice** for a released commit: once on its push to
  `master`, again on the tag.
- **The release job needs `contents: write`** to create the GitHub Release.
- **A tag pushed by mistake releases.** It must still be a valid version on
  `master`, but a wrong number is shipped under that name; delete the
  release and the tag, and push the right one.

## Alternatives considered

- **Keep releasing every merge (0055).** It needs no step from anyone, but
  pays the release job for builds no place pulls, and leaves nothing to cut
  a hotfix from.
- **A manual `workflow_dispatch` release.** It avoids the second gate run,
  but a button press leaves nothing in git, so the version a place runs is
  not a ref anyone can check out or branch from.
- **Release on a published GitHub Release.** The same as a tag, with the
  notes written first; but it lives only on GitHub, whereas a tag can be
  pushed from any clone. The job creates the Release from the tag instead.
- **CalVer (`2026.10.0`).** It avoids deciding what counts as breaking, but
  SemVer's major number also says when a place needs more than a pull, such
  as a migration that cannot be rolled back.
