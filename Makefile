# Standard targets required by design-guideline/ai-context/shared-context.md.
#
#   build-infra -> build-app -> start-infra -> [migrate] -> start-app
#   shutdown:    stop-app -> stop-infra
#
# Build never starts. Start never builds. Test neither builds nor starts.
# App targets never start infra. Every target is idempotent and fed from .env.
#
# Everything runs in a container. A contributor installs Docker and make, and
# nothing else — no Python, no Node, no psql, no linter. If you find yourself
# wanting to run a tool directly, a target is missing.
#
# Modes. `build-app`, `start-app` and `stop-app` take MODE=dev|prod, default
# prod; anything else fails.
#   prod  the `prod` stage, compose.yaml alone, nothing mounted. What CI and
#         every deployed environment use, and what `scan` scans.
#   dev   the `dev` stage, compose.yaml + compose.dev.yaml: the repo
#         bind-mounted, reloading on save. Local only.
# Tests and gates ignore MODE: they always run the `test` stage, never mounted,
# which `build-app` builds in either mode. The app itself never reads MODE.
#
# Places. What runs here is COMPOSE_PROFILES in .env, not a make variable
# (docs/decisions/0051): `edge` (api, web, Postgres), `compute` (worker,
# crawler), `tunnel` (the link between them), `proxy` (Caddy, ADR 0053) and
# `local` (MinIO). Development and CI name edge, compute and local. Builds and `stop-app` cover every profile;
# starts run only this place's.

SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV_FILE      ?= .env
INFRA_COMPOSE := infra/compose.yml
NETWORK       := jsa_net

MODE ?= prod

COMPOSE_BASE := docker compose --env-file $(ENV_FILE) -f compose.yaml
COMPOSE_DEV  := $(COMPOSE_BASE) -f compose.dev.yaml
ifeq ($(MODE),dev)
COMPOSE_APP  := $(COMPOSE_DEV)
else
COMPOSE_APP  := $(COMPOSE_BASE)
endif
COMPOSE_INFRA := docker compose --env-file $(ENV_FILE) -f $(INFRA_COMPOSE)
# Every profile, whatever this place runs: what builds, stops and reports use.
ALL_PROFILES  := --profile '*'

# One tag per mode, plus the test image both modes build.
MODE_IMAGES        := jsa-backend:$(MODE) jsa-web:$(MODE)
PROD_IMAGES        := jsa-backend:prod jsa-web:prod jsa-proxy:prod
PROXY_IMAGE        := jsa-proxy:prod
BACKEND_TEST_IMAGE := jsa-backend:test
WEB_TEST_IMAGE     := jsa-web:test
SCANNER_IMAGE      := aquasec/trivy:0.74.0

# The dev overlay's source-writing tools run as the invoking user, so the files
# they rewrite stay owned by that user on every host.
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)

# Hermetic: no network at all, so a unit test cannot reach infra by accident.
RUN_HERMETIC := docker run --rm --network none
# On the compose network, with configuration supplied at run time.
RUN_ON_NET   := docker run --rm --network $(NETWORK) --env-file $(ENV_FILE)

PATTERN ?=
ifdef PATTERN
PYTEST_FILTER := -k $(PATTERN)
VITEST_FILTER := -t $(PATTERN)
else
PYTEST_FILTER :=
VITEST_FILTER :=
endif

.PHONY: help require-env check-mode require-mode-images require-app-services \
        require-infra-services build-infra build-app \
        start-infra start-app stop-app stop-infra test-unit test-integration \
        migrate lint typecheck scan format gen-client lock clean-up-infra logs \
        stats disk-usage clean-up-cache backup-db restore-db push-app pull-app

help:
	@echo "Standard targets (build-app, start-app, stop-app take MODE=dev|prod):"
	@echo "  build-infra build-app start-infra start-app stop-app stop-infra"
	@echo "  test-unit test-integration"
	@echo "Gates (their own targets, never folded into a test target):"
	@echo "  lint typecheck scan"
	@echo "Supporting targets (never dependencies of the above):"
	@echo "  migrate format gen-client lock logs stats disk-usage backup-db"
	@echo "  push-app (CI) pull-app (each deployed place)"
	@echo "  clean-up-cache clean-up-infra restore-db (the last two destructive)"

require-env:
	@test -f $(ENV_FILE) || { \
	  echo "ERROR: $(ENV_FILE) is missing. Copy .env.example to .env and fill it in."; \
	  exit 1; }

check-mode:
	@case "$(MODE)" in dev|prod) ;; \
	  *) echo "ERROR: MODE must be dev or prod, got '$(MODE)'."; exit 1 ;; esac

# Start never builds: it fails here, with the command to run, when the image
# for the requested mode is missing.
require-mode-images: check-mode
	@for image in $(MODE_IMAGES); do \
	  docker image inspect $$image >/dev/null 2>&1 || { \
	    echo "ERROR: $$image is missing. Run: make build-app MODE=$(MODE)"; exit 1; }; \
	done

# A place whose COMPOSE_PROFILES selects nothing would start nothing and say
# nothing; fail instead, with what to set.
require-app-services: require-env
	@[ -n "$$($(COMPOSE_BASE) config --services 2>/dev/null | grep -vx migrate)" ] || { \
	  echo "ERROR: COMPOSE_PROFILES in $(ENV_FILE) selects no app service."; \
	  echo "  Set edge, compute, or both (development: edge,compute,local)."; exit 1; }

require-infra-services: require-env
	@[ -n "$$($(COMPOSE_INFRA) config --services 2>/dev/null)" ] || { \
	  echo "ERROR: COMPOSE_PROFILES in $(ENV_FILE) selects no infra service."; \
	  echo "  Set edge, tunnel or local (development: edge,compute,local)."; exit 1; }

# --- build ------------------------------------------------------------------

# This place's infra only: a compute machine has no use for Postgres's image.
build-infra: require-infra-services
	$(COMPOSE_INFRA) pull

# The images for the requested mode, plus the `test` stage the test tiers and
# gates run in — built whichever mode was asked for. The proxy has one stage,
# so it is jsa-proxy:prod in either mode; only a `proxy` place runs it.
build-app: require-env check-mode
	$(COMPOSE_APP) $(ALL_PROFILES) build
	docker build --target test -t $(BACKEND_TEST_IMAGE) backend
	docker build --target test -t $(WEB_TEST_IMAGE) web
	docker pull $(SCANNER_IMAGE)

# --- start / stop -----------------------------------------------------------

# jsa_net is created here even where no infra service joins it (a compute
# machine runs only the tunnel, on the host's network), because the app's
# compose file expects it.
start-infra: require-infra-services
	@infra/tunnel-up.sh check
	@docker network inspect $(NETWORK) >/dev/null 2>&1 || docker network create $(NETWORK) >/dev/null
	$(COMPOSE_INFRA) up -d
	@echo "Waiting for infra to report healthy..."
	@infra/wait-for-healthy.sh
	@infra/tunnel-up.sh
	@infra/bootstrap-roles.sh

# Both modes migrate first: pending migrations run to completion BEFORE any
# container serves traffic, and a failed migration fails the start. Starting
# one mode replaces the other, since both run the same services.
start-app: require-app-services require-mode-images migrate
	$(COMPOSE_APP) up -d --no-build
	@echo "MODE=$(MODE), running here:"
	@$(COMPOSE_APP) ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'

# Stops whichever mode is running: both run the same services in one project.
stop-app: require-env check-mode
	$(COMPOSE_BASE) $(ALL_PROFILES) down --remove-orphans

# Preserves data on purpose. Use `make clean-up-infra` to discard volumes.
stop-infra: require-env
	$(COMPOSE_INFRA) $(ALL_PROFILES) stop

logs: require-env
	$(COMPOSE_BASE) $(ALL_PROFILES) logs --tail 100 -f

# --- resource usage ---------------------------------------------------------

# One snapshot of CPU, memory and processes for this stack's containers, both
# projects, against the limits the compose files set (MEM % is of the limit).
# Then restarts and OOM kills: a non-zero count means a limit is too tight or
# something leaks — raise the *_MEM_LIMIT in .env, or find the leak.
stats: require-env
	@ids="$$($(COMPOSE_INFRA) $(ALL_PROFILES) ps -q) $$($(COMPOSE_BASE) $(ALL_PROFILES) ps -q)"; \
	 [ -n "$${ids// /}" ] || { echo "Nothing is running. Run: make start-infra"; exit 1; }; \
	 docker stats --no-stream \
	   --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}' $$ids; \
	 echo; \
	 docker inspect --format '{{.Name}}  restarts={{.RestartCount}}  oom_killed={{.State.OOMKilled}}' \
	   $$ids | sed 's|^/||'

# Where the disk goes: free space, volume sizes, the largest Postgres
# relations, and object storage by bucket. Read-only. Needs infra up.
disk-usage: require-env
	@infra/disk-usage.sh

# --- migrations -------------------------------------------------------------

# A one-off container from the mode's own image. In dev it sees the mounted
# source, so a migration written a moment ago applies without a rebuild.
migrate: require-env require-mode-images
	$(COMPOSE_APP) run --rm migrate

# --- test -------------------------------------------------------------------

# Hermetic: no infra, no network, no running app. Must pass on a clean checkout.
test-unit:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) pytest tests/unit $(PYTEST_FILTER)
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx vitest run $(VITEST_FILTER)

# Assumes infra is already up and migrated. Never starts infra itself.
test-integration: require-env
	$(RUN_ON_NET) $(BACKEND_TEST_IMAGE) pytest tests/integration $(PYTEST_FILTER)

# --- gates ------------------------------------------------------------------

lint:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) ruff check .
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) ruff format --check .
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) lint-imports --config .importlinter \
	    --cache-dir /tmp/import-linter
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx eslint src
	$(RUN_HERMETIC) -e SITE_HOSTNAME=lint.invalid $(PROXY_IMAGE) \
	    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

# web/tsconfig.json lists no files, only a reference to tsconfig.app.json, so a
# bare `tsc --noEmit` there checks nothing. Name the project that holds src/.
typecheck:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) mypy .
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx tsc -p tsconfig.app.json --noEmit

# Dependencies, and the prod images themselves: prod is what gets promoted, so
# prod is what gets scanned.
#
# The images reach Trivy as a `docker save` stream on stdin rather than by
# mounting the Docker socket, which would hand the scanner root on the host.
#
# pip-audit runs without --strict on purpose: torch is installed from the
# CPU-only wheel index, and its local version (`2.14.0+cpu`) has no PyPI entry
# to look up. Coverage for it comes from the image scan below, which reads the
# installed packages directly — so nothing is unscanned, and the strict flag is
# not quietly hiding a real advisory.
scan:
	@for image in $(PROD_IMAGES); do \
	  docker image inspect $$image >/dev/null 2>&1 || { \
	    echo "ERROR: $$image is missing; scan covers the prod images. Run: make build-app"; exit 1; }; \
	done
	docker run --rm $(BACKEND_TEST_IMAGE) pip-audit
	docker run --rm $(WEB_TEST_IMAGE) npm audit --audit-level=high
	@for image in $(PROD_IMAGES); do \
	  echo "trivy: $$image"; \
	  docker save $$image | docker run --rm -i --entrypoint sh $(SCANNER_IMAGE) -c \
	    'cat > /tmp/image.tar && trivy image --quiet --input /tmp/image.tar \
	       --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed' \
	    || exit 1; \
	done

# --- supporting targets -----------------------------------------------------

# Applies formatting. It writes to source, so it runs through the dev overlay,
# where every source mount lives; the `lint` gate that checks formatting never
# mounts anything. Needs the dev images: `make build-app MODE=dev`.
format: require-env
	@$(MAKE) --no-print-directory require-mode-images MODE=dev
	$(COMPOSE_DEV) run --rm backend-tools sh -c 'ruff check --fix . && ruff format .'
	$(COMPOSE_DEV) run --rm web-tools npx prettier --write "src/**/*.{ts,tsx}" --log-level warn

# Regenerates the checked-in API client from the API's OpenAPI document.
# Mount-free: the document leaves one container on stdout and enters the next
# on stdin, so it runs from the test images and works in CI.
gen-client: require-env
	$(RUN_HERMETIC) --env-file $(ENV_FILE) $(BACKEND_TEST_IMAGE) \
	    python -m cli.export_openapi > web/openapi.json
	$(RUN_HERMETIC) -i $(WEB_TEST_IMAGE) sh -c \
	    'cat > /tmp/openapi.json && npx openapi-typescript /tmp/openapi.json -o /tmp/schema.d.ts >&2 && cat /tmp/schema.d.ts' \
	    < web/openapi.json > web/src/api/schema.d.ts.tmp \
	  && mv web/src/api/schema.d.ts.tmp web/src/api/schema.d.ts \
	  || { rm -f web/src/api/schema.d.ts.tmp; exit 1; }

# Regenerates backend/uv.lock after a dependency change. It writes to source,
# so it runs through the dev overlay. Needs the dev images: `make build-app MODE=dev`.
lock: require-env
	@$(MAKE) --no-print-directory require-mode-images MODE=dev
	$(COMPOSE_DEV) run --rm backend-tools uv lock

# Deletes the tool caches left in the checkout: bytecode, the pytest, mypy,
# ruff and import-linter caches, downloaded embedding models (.cache/) and the
# web build output. Everything it removes is regenerated on the next run, and
# no data or configuration is touched: .env, tmp/, installed dependencies
# (.venv/, node_modules/) and web/openapi.json stay. Package directories left
# holding nothing once their bytecode is gone are removed too.
#
# Plain find/rm on the host rather than a container: it only deletes files in
# this checkout, and a container would need the checkout bind-mounted, which is
# only ever done in compose.dev.yaml.
CACHE_DIRS := __pycache__ .pytest_cache .mypy_cache .ruff_cache .import_linter_cache .cache

# Never descends into .git, tmp/ or installed dependencies. No -delete here:
# it implies -depth, and -depth silently disables -prune.
KEEP_OUT := -name .git -o -name tmp -o -name node_modules -o -name .venv

clean-up-cache:
	find . -mindepth 1 \( $(KEEP_OUT) \) -prune -o -type d \
	    \( $(foreach d,$(CACHE_DIRS),-name $(d) -o) -false \) -print -prune -exec rm -rf {} +
	find . -mindepth 1 \( $(KEEP_OUT) \) -prune -o -type f -name '*.py[cod]' -print -exec rm -f {} +
	rm -rf web/dist
	find backend -mindepth 1 -depth -type d -empty -not -path '*/.venv/*' -print -exec rmdir {} \;

# --- releases (ADR 0055) -----------------------------------------------------

# CI only, after every gate has passed: builds the prod images for every
# platform in RELEASE_PLATFORMS, pushes them to RELEASE_REGISTRY and writes
# release.env, each image by digest. Needs a buildx builder that can build
# those platforms.
push-app: require-env
	@infra/push-release.sh

# On the droplet and the compute machine, in place of build-app: pulls the
# release CI pushed, by digest, and tags it jsa-*:prod for start-app.
pull-app:
	@infra/pull-release.sh "$(RELEASE)"

# --- backups ----------------------------------------------------------------

# One pg_dump of the database, into the backup bucket (BACKUP_S3_*). Only
# reads the database; run it where Postgres runs. The droplet's crontab runs
# it nightly; the bucket's lifecycle rule decides how long dumps are kept.
backup-db: require-env
	@infra/backup-db.sh

# DESTRUCTIVE: replaces a database with a dump from the backup bucket.
# BACKUP= names the dump (`make backup-db` prints it); RESTORE_DB= the
# database to restore into, default POSTGRES_DB. Stop the app first. Never a
# dependency of anything.
restore-db: require-env
	@infra/restore-db.sh "$(BACKUP)" "$(RESTORE_DB)"

# DESTRUCTIVE. Never a dependency of a build, start, stop or test target.
clean-up-infra: require-env
	@read -p "This deletes all local infra volumes. Type 'yes' to continue: " ok; \
	 [ "$$ok" = "yes" ] || { echo "aborted"; exit 1; }
	$(COMPOSE_BASE) $(ALL_PROFILES) down --remove-orphans
	$(COMPOSE_INFRA) $(ALL_PROFILES) down -v
