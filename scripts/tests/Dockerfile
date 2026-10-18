# The host scripts' tests (`make test-unit`). The scripts drive git, make,
# Docker and SSH on a deployed machine; here they run against a throwaway git
# repository and fake commands that record what they were asked to do, so the
# tests need nothing but Python's standard library and git, and no network.
#
# Built by `make build-app` from scripts/ alone; never mounted.
FROM python:3.12.14-slim-bookworm

# git as Debian ships it: a test tool that never reaches production, so it
# follows bookworm's security updates rather than a pin.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home tester

COPY --chown=tester:tester . /scripts
WORKDIR /scripts
USER tester
ENV GIT_AUTHOR_NAME=tester GIT_AUTHOR_EMAIL=tester@example.invalid \
    GIT_COMMITTER_NAME=tester GIT_COMMITTER_EMAIL=tester@example.invalid \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "unittest", "discover", "-s", "tests"]
