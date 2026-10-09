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
# Machines (docs/decisions/0062). What runs here, how big it is and under which
# names is the machine's folder in deploy/, named by the one line in .machine
# (git-ignored; .machine.example says `local`):
#   local               a developer's laptop: every service, the `dev` images,
#                       the source bind-mounted and reloading on save
#   ci                  CI's runner: every service but the proxy, the `prod`
#                       images, nothing mounted
#   droplet-1vcpu-2gb   api, web, proxy, Postgres and the tunnel (ADR 0051)
#   compute-m5pro-48gb  worker, crawler and the tunnel (ADR 0051)
# .env holds only what the application reads, and secrets; nothing about the
# machine's shape. The machine decides the image too, so there is no MODE: local
# runs the `dev` stage, every other machine `prod`. Tests and gates always run
# the `test` stage, never mounted, which `build-app` builds on every machine.
# The app itself never reads which machine it is on.

SHELL := /bin/bash
.DEFAULT_GOAL := help

ifeq ($(origin MODE),command line)
$(error MODE is gone (docs/decisions/0062): the machine named in .machine decides. local runs the dev images, every other machine the prod ones)
endif

ENV_FILE := .env

MACHINE            := $(strip $(shell cat .machine 2>/dev/null))
MACHINE_DIR        := deploy/$(MACHINE)
APP_COMPOSE_FILE   := $(MACHINE_DIR)/compose.app.yaml
INFRA_COMPOSE_FILE := $(MACHINE_DIR)/compose.infra.yaml
LOCAL_COMPOSE_FILE := deploy/local/compose.app.yaml

# The names this machine's files give the two compose projects and their
# shared network, read from the files themselves so they are written once.
APP_PROJECT   := $(shell sed -n 's/^name: *//p' $(APP_COMPOSE_FILE) 2>/dev/null)
INFRA_PROJECT := $(shell sed -n 's/^name: *//p' $(INFRA_COMPOSE_FILE) 2>/dev/null)
NETWORK       := $(shell sed -n '/^networks:/,/^[^ ]/s/^    name: *//p' $(INFRA_COMPOSE_FILE) 2>/dev/null)
# The scripts run compose against the same files and network.
export ENV_FILE INFRA_COMPOSE_FILE NETWORK APP_PROJECT INFRA_PROJECT

COMPOSE_APP   := docker compose --env-file $(ENV_FILE) -f $(APP_COMPOSE_FILE)
COMPOSE_INFRA := docker compose --env-file $(ENV_FILE) -f $(INFRA_COMPOSE_FILE)
# The source-writing tools live with the source mounts, in local's file.
COMPOSE_LOCAL := docker compose --env-file $(ENV_FILE) -f $(LOCAL_COMPOSE_FILE)
# Every profile: the one-off `migrate` and local's `tools` included. What
# builds, stops and reports use.
ALL_PROFILES  := --profile '*'

PROD_IMAGES        := careerpolaris-backend:prod careerpolaris-web:prod careerpolaris-proxy:prod
DEV_IMAGES         := careerpolaris-backend:dev careerpolaris-web:dev
PROXY_IMAGE        := careerpolaris-proxy:prod
BACKEND_TEST_IMAGE := careerpolaris-backend:test
WEB_TEST_IMAGE     := careerpolaris-web:test
SCANNER_IMAGE      := aquasec/trivy:0.74.0

# Local's source-writing tools run as the invoking user, so the files they
# rewrite stay owned by that user on every host.
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)

# Hermetic: no network at all, so a unit test cannot reach infra by accident.
RUN_HERMETIC := docker run --rm --network none
# On this machine's compose network, with configuration supplied at run time.
RUN_ON_NET   := docker run --rm --network $(NETWORK) --env-file $(ENV_FILE)

CHECK_ENV_IMAGE := careerpolaris-backend:prod

PATTERN ?=
ifdef PATTERN
PYTEST_FILTER := -k $(PATTERN)
VITEST_FILTER := -t $(PATTERN)
else
PYTEST_FILTER :=
VITEST_FILTER :=
endif

.PHONY: help require-env require-machine require-own-stack require-machine-images \
        require-dev-images build-infra build-app \
        start-infra start-app stop-app stop-infra test-unit test-integration \
        migrate lint typecheck scan format gen-client lock clean-up-infra logs \
        stats disk-usage clean-up-cache backup-db restore-db release push-app pull-app \
        check-env

help:
	@echo "This checkout's machine: $(if $(MACHINE),$(MACHINE),none — cp .machine.example .machine)"
	@echo "Standard targets:"
	@echo "  build-infra build-app start-infra start-app stop-app stop-infra"
	@echo "  test-unit test-integration"
	@echo "Gates (their own targets, never folded into a test target):"
	@echo "  lint typecheck scan"
	@echo "Supporting targets (never dependencies of the above):"
	@echo "  migrate format gen-client lock logs stats disk-usage backup-db check-env"
	@echo "  release BUMP=patch|minor|major (you) push-app (CI) pull-app (each deployed place)"
	@echo "  clean-up-cache clean-up-infra restore-db (the last two destructive)"

require-env:
	@test -f $(ENV_FILE) || { \
	  echo "ERROR: $(ENV_FILE) is missing. Copy .env.example to .env and fill it in."; \
	  exit 1; }

# Which machine this checkout is: one line in .machine, naming a folder in
# deploy/ that holds both compose files.
require-machine: require-env
	@[ -n "$(MACHINE)" ] || { \
	  echo "ERROR: .machine is missing. A laptop: cp .machine.example .machine"; \
	  echo "  A deployed place: echo <machine> > .machine, one of:"; \
	  echo "  $(sort $(patsubst deploy/%/compose.app.yaml,%,$(wildcard deploy/*/compose.app.yaml)))"; \
	  exit 1; }
	@[ -f "$(APP_COMPOSE_FILE)" ] && [ -f "$(INFRA_COMPOSE_FILE)" ] || { \
	  echo "ERROR: .machine says '$(MACHINE)', which has no compose.app.yaml and compose.infra.yaml in deploy/."; \
	  echo "  Machines: $(sort $(patsubst deploy/%/compose.app.yaml,%,$(wildcard deploy/*/compose.app.yaml)))"; \
	  exit 1; }

# A stack belongs to the checkout that started it. Two clones on one host (a
# deployment and a development one) use different machines and so different
# names; this refuses to start or stop a stack another checkout started, which
# is what a clone pointed at the wrong machine would otherwise do.
require-own-stack: require-machine
	@scripts/check-stack-owner.sh

# Start never builds: it fails here, with the command to run, when an image
# this machine runs is missing.
require-machine-images: require-machine
	@for image in $$($(COMPOSE_APP) $(ALL_PROFILES) config --images 2>/dev/null | sort -u); do \
	  docker image inspect $$image >/dev/null 2>&1 || { \
	    echo "ERROR: $$image is missing. Run: make build-app"; \
	    echo "  (a deployed place pulls its release instead: make pull-app RELEASE=release.env)"; exit 1; }; \
	done

# `format` and `lock` run local's tools, whatever machine this checkout is.
require-dev-images:
	@for image in $(DEV_IMAGES); do \
	  docker image inspect $$image >/dev/null 2>&1 || { \
	    echo "ERROR: $$image is missing. Run make build-app in a checkout whose .machine is local."; exit 1; }; \
	done

# --- build ------------------------------------------------------------------

# This machine's infra images only: a compute machine has no use for Postgres's.
build-infra: require-machine
	$(COMPOSE_INFRA) pull

# The images this machine runs, plus the `test` stage the test tiers and gates
# run in and the proxy image `lint` validates the Caddyfile with — on every
# machine. local builds the `dev` stage; every other machine `prod`.
build-app: require-machine
	$(COMPOSE_APP) $(ALL_PROFILES) build
	docker build --target test -t $(BACKEND_TEST_IMAGE) backend
	docker build --target test -t $(WEB_TEST_IMAGE) web
	docker build --target prod -t $(PROXY_IMAGE) proxy
	docker pull $(SCANNER_IMAGE)

# --- start / stop -----------------------------------------------------------

# The network is created here even where no infra service joins it (a compute
# machine runs only the tunnel, on the host's network), because the app's
# compose file expects it.
start-infra: require-own-stack
	@scripts/tunnel-up.sh check
	@docker network inspect $(NETWORK) >/dev/null 2>&1 || docker network create $(NETWORK) >/dev/null
	$(COMPOSE_INFRA) up -d
	@echo "Waiting for infra to report healthy..."
	@scripts/wait-for-healthy.sh
	@scripts/tunnel-up.sh
	@scripts/bootstrap-roles.sh

# Pending migrations run to completion BEFORE any container serves traffic,
# and a failed migration fails the start.
start-app: require-own-stack require-machine-images migrate
	$(COMPOSE_APP) up -d --no-build
	@echo "$(MACHINE), running here:"
	@$(COMPOSE_APP) ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'

stop-app: require-own-stack
	$(COMPOSE_APP) $(ALL_PROFILES) down --remove-orphans

# Preserves data on purpose. Use `make clean-up-infra` to discard volumes.
stop-infra: require-own-stack
	$(COMPOSE_INFRA) $(ALL_PROFILES) stop

logs: require-machine
	$(COMPOSE_APP) $(ALL_PROFILES) logs --tail 100 -f

# --- resource usage ---------------------------------------------------------

# One snapshot of CPU, memory and processes for this stack's containers, both
# projects, against the limits the machine's files set (MEM % is of the limit).
# Then restarts and OOM kills: a non-zero count means a limit is too tight or
# something leaks — raise it in deploy/$(MACHINE)/, by pull request, or find
# the leak.
stats: require-machine
	@ids="$$($(COMPOSE_INFRA) $(ALL_PROFILES) ps -q) $$($(COMPOSE_APP) $(ALL_PROFILES) ps -q)"; \
	 [ -n "$${ids// /}" ] || { echo "Nothing is running. Run: make start-infra"; exit 1; }; \
	 docker stats --no-stream \
	   --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}' $$ids; \
	 echo; \
	 docker inspect --format '{{.Name}}  restarts={{.RestartCount}}  oom_killed={{.State.OOMKilled}}' \
	   $$ids | sed 's|^/||'

# Where the disk goes: free space, volume sizes, the largest Postgres
# relations, and object storage by bucket. Read-only. Needs infra up.
disk-usage: require-machine
	@scripts/disk-usage.sh

# --- migrations -------------------------------------------------------------

# A one-off container from this machine's own image. On local it sees the
# mounted source, so a migration written a moment ago applies without a rebuild.
migrate: require-own-stack require-machine-images
	$(COMPOSE_APP) run --rm migrate

# --- test -------------------------------------------------------------------

# Hermetic: no infra, no network, no running app. Must pass on a clean checkout.
test-unit:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) pytest tests/unit $(PYTEST_FILTER)
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx vitest run $(VITEST_FILTER)

# Assumes infra is already up and migrated. Never starts infra itself.
test-integration: require-machine
	@docker network inspect $(NETWORK) >/dev/null 2>&1 || { \
	  echo "ERROR: $(NETWORK) does not exist: infra is not up. Run: make start-infra"; exit 1; }
	$(RUN_ON_NET) $(BACKEND_TEST_IMAGE) pytest tests/integration $(PYTEST_FILTER)

# --- gates ------------------------------------------------------------------

# The code, the Caddyfile, and every machine's compose files: each must render
# against .env.example's names, extend only services the bases define, and
# share one network between its app and infra projects; and .env.example must
# hold nothing about a machine's shape (ADR 0062).
lint:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) ruff check .
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) ruff format --check .
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) lint-imports --config .importlinter \
	    --cache-dir /tmp/import-linter
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx eslint src
	$(RUN_HERMETIC) -e SITE_HOSTNAME=lint.invalid $(PROXY_IMAGE) \
	    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
	@scripts/check-deploy.sh

# web/tsconfig.json lists no files, only a reference to tsconfig.app.json, so a
# bare `tsc --noEmit` there checks nothing. Name the project that holds src/.
typecheck:
	$(RUN_HERMETIC) $(BACKEND_TEST_IMAGE) mypy .
	$(RUN_HERMETIC) $(WEB_TEST_IMAGE) npx tsc -p tsconfig.app.json --noEmit

# Dependencies, and the prod images themselves: prod is what gets promoted, so
# prod is what gets scanned. The prod images are built on the `ci` machine (or
# pulled on a deployed one); a `local` checkout has only the dev images.
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
	    echo "ERROR: $$image is missing; scan covers the prod images."; \
	    echo "  Run make build-app in a checkout whose .machine is ci (CI does)."; exit 1; }; \
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

# Applies formatting. It writes to source, so it runs through local's file,
# where every source mount lives; the `lint` gate that checks formatting never
# mounts anything. Needs the dev images.
format: require-env require-dev-images
	$(COMPOSE_LOCAL) run --rm backend-tools sh -c 'ruff check --fix . && ruff format .'
	$(COMPOSE_LOCAL) run --rm web-tools npx prettier --write "src/**/*.{ts,tsx}" --log-level warn

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
# so it runs through local's file. Needs the dev images.
lock: require-env require-dev-images
	$(COMPOSE_LOCAL) run --rm backend-tools uv lock

# Deletes the tool caches left in the checkout: bytecode, the pytest, mypy,
# ruff and import-linter caches, downloaded embedding models (.cache/) and the
# web build output. Everything it removes is regenerated on the next run, and
# no data or configuration is touched: .env, .machine, tmp/, installed
# dependencies (.venv/, node_modules/) and web/openapi.json stay. Package
# directories left holding nothing once their bytecode is gone are removed too.
#
# Plain find/rm on the host rather than a container: it only deletes files in
# this checkout, and a container would need the checkout bind-mounted, which is
# only ever done in deploy/local/compose.app.yaml.
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

# --- releases (ADR 0055, 0060) -----------------------------------------------

# For the operator: tags origin/master with the next version
# (BUMP=patch|minor|major) and pushes the tag, which starts CI's release.
# Idempotent: does nothing if origin/master is already released, and pushes a
# tag an earlier run left unpushed. Asks first; YES=1 does not. Runs git on the
# host, with your own credentials.
release:
	@BUMP="$(BUMP)" YES="$(YES)" scripts/tag-release.sh

# CI only, for a version tag on master after every gate has passed: builds the
# prod images for every platform in RELEASE_PLATFORMS, pushes them to
# RELEASE_REGISTRY under the version and writes release.env, each image by
# digest. Refuses a HEAD with no vX.Y.Z tag or not on origin/master. Needs a buildx builder that can build
# those platforms.
push-app: require-env
	@scripts/push-release.sh

# On the droplet and the compute machine, in place of build-app: pulls the
# release CI pushed, by digest, and tags it careerpolaris-*:prod for start-app.
pull-app:
	@scripts/pull-release.sh "$(RELEASE)"

# On a deployed place: compares its .env with .env.example. Fails on a name
# .env lacks or a required value left blank (.env.example's `# may-be-blank:`
# line names the optional ones), and lists values that differ from
# .env.example's. Run it once .env is filled in, and after each release. Prints
# no secret: only values .env.example sets, and it leaves every secret blank.
check-env: require-env
	@docker image inspect $(CHECK_ENV_IMAGE) >/dev/null 2>&1 || { \
	  echo "ERROR: $(CHECK_ENV_IMAGE) is missing. Run: make pull-app RELEASE=release.env"; exit 1; }
	@for f in .env.example $(ENV_FILE); do echo "### FILE $$f"; cat "$$f"; echo; done \
	  | $(RUN_HERMETIC) -i $(CHECK_ENV_IMAGE) sh -c "$$(cat scripts/check-env.sh)" \
	      check-env .env.example $(ENV_FILE)

# --- backups ----------------------------------------------------------------

# One pg_dump of the database, into the backup bucket (BACKUP_S3_*). Only
# reads the database; run it where Postgres runs. The droplet's crontab runs
# it nightly; the bucket's lifecycle rule decides how long dumps are kept.
backup-db: require-machine
	@scripts/backup-db.sh

# DESTRUCTIVE: replaces a database with a dump from the backup bucket.
# BACKUP= names the dump (`make backup-db` prints it); RESTORE_DB= the
# database to restore into, default POSTGRES_DB. Stop the app first. Never a
# dependency of anything.
restore-db: require-own-stack
	@scripts/restore-db.sh "$(BACKUP)" "$(RESTORE_DB)"

# DESTRUCTIVE. Never a dependency of a build, start, stop or test target.
clean-up-infra: require-own-stack
	@read -p "This deletes every infra volume of $(INFRA_PROJECT) ($(MACHINE)). Type 'yes' to continue: " ok; \
	 [ "$$ok" = "yes" ] || { echo "aborted"; exit 1; }
	$(COMPOSE_APP) $(ALL_PROFILES) down --remove-orphans
	$(COMPOSE_INFRA) $(ALL_PROFILES) down -v
