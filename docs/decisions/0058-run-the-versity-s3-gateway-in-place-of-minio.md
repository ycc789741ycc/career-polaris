# 0058. Development and CI run the Versity S3 Gateway, not MinIO

**Status:** Accepted — 2026-10-05.

## Context

Development and CI store files in a local S3 server, the `local` profile,
which stands in for Spaces or R2 (ADR 0051). That server was MinIO, pinned to
`quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` after its Docker Hub
repository went away.

MinIO no longer publishes images anyone can pull. Docker Hub has no
`minio/minio`, and quay.io answers 401 to anonymous requests. A machine that
has the image cached still runs, but `make build-infra` fails everywhere,
and a fresh machine or CI cannot start the stack at all.

The app uses a narrow part of S3:

- `HeadBucket` and `CreateBucket`;
- put, get and delete of objects;
- presigned GET links with an attachment filename, signed against
  `S3_PUBLIC_ENDPOINT_URL`, with path-style addressing.

## Decision

The `objectstore` service runs the **Versity S3 Gateway**
(`versity/versitygw:v1.8.0`, Apache-2.0), with its POSIX backend under
`/data`.

- **It keeps each object as a plain file.** It lives in a new volume,
  `objectfiles`, not MinIO's `objectdata`, whose format it cannot read.
- **Keys come from `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`,** as before.
  `S3_ENDPOINT_URL` and the published port 21473 do not change.
- **There is no web console.** `S3_CONSOLE_PUBLISHED_PORT` and port 21474
  are gone, and the repo's port block is 21470–21473.
- **It runs read-only,** with every capability dropped and
  `no-new-privileges`. Its health check is a TCP probe, because the gateway
  answers an unsigned request with 403.
- **Found on the way:** only the api created the bucket, at startup, so on
  fresh infra five integration tests failed, whatever the server. The
  integration tier now makes sure the bucket exists once per session
  (`tests/integration/conftest.py`).

Checked against it:

- `HeadBucket` returns 404 for a missing bucket, then create, put, get and
  delete work.
- A presigned link carrying `Content-Disposition` downloads, and a tampered
  one is refused with 403.
- All 149 integration tests pass on fresh infra.

## Consequences

Easier:

- **A pinned image that can be pulled again,** so `build-infra` and CI work
  on any machine.
- **About 30 MB and a few dozen MB of memory,** where MinIO took around
  150 MB. Its ceiling falls from 1 GB to 256 MB.
- **Files on disk are the objects themselves,** readable with `ls` and `du`.

Harder:

- **Files stored in local MinIO do not carry over.** That means uploaded
  résumé files and PDF exports. Their database rows stay, so an old export's
  link fails until it is exported again. A machine can copy its files across
  once, by hand.
- **No console** for browsing buckets. `make disk-usage` and `ls` in the
  container replace it.
- **The gateway runs as root inside its container,** to own the volume
  Docker creates root-owned. It has no capabilities and cannot gain any.
- **It is a smaller project than MinIO.** If it stops being maintained, the
  next replacement is again a one-service change, because the app speaks
  only plain S3.

## Alternatives considered

- **Keep MinIO, built from source in a Dockerfile.** The AGPL source is still
  public, but it means a Go build of a large project, kept up to date by us,
  for a development stand-in.
- **SeaweedFS.** Its S3 gateway works, but it is a cluster of master, volume
  and filer, and its Docker Hub tags are not plain versions to pin.
- **Garage.** A good fit for small clusters, but it needs a layout set up and
  keys created through its CLI before the first request.
- **RustFS.** MinIO-compatible and on Docker Hub, but it reached 1.0 only
  recently.
- **Zenko CloudServer and LocalStack.** CloudServer is heavier, and its tags
  are not plain versions to pin. LocalStack keeps nothing across restarts
  without a paid plan.
