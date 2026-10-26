# The SPA image.
#
# The built bundle carries no configuration: `docker-entrypoint.d` writes
# `config.js` from the environment at container start, so the same artifact is
# promoted through every environment (shared-context: Configuration — prefer
# run-time config over build-time inlining).
#
# Three images from this one file:
#
#   prod  nginx serving the built bundle, non-root. The default, and the only
#         image CI or a deployed environment uses. Last stage on purpose.
#   test  Node with every dependency and the source: lint, typecheck,
#         test-unit and gen-client run here, never mounted. The SPA's
#         production artifact is static files, so "prod plus test deps" means
#         the source `build` compiles, with the tools that check it.
#   dev   test plus the Vite dev server, run on the `local` machine with
#         web/src bind-mounted. Never pushed, never deployed.

# --- dependencies ----------------------------------------------------------
FROM node:26.9.0-bookworm-slim AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci


# --- test: lint, typecheck, unit tests, client generation ------------------
FROM deps AS test

COPY . /app
# Vitest writes a transient config file into the working directory, so the
# directory itself must be writable by the unprivileged user. Not recursive:
# node_modules stays root-owned and read-only.
RUN chown node:node /app
USER node


# --- dev: the Vite dev server with hot module replacement -----------------
# Listens on 8080, the port the prod image uses, so compose's published port
# mapping reads the same on every machine.
FROM test AS dev

CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "8080", "--strictPort"]


# --- build -----------------------------------------------------------------
FROM deps AS build

COPY . /app
RUN npm run build


# --- prod ------------------------------------------------------------------
# Unprivileged nginx: runs as uid 101, no root anywhere in the chain.
FROM nginxinc/nginx-unprivileged:1.31.6-alpine AS prod

# uid 101 is the unprivileged `nginx` user this image runs as. The document
# root must be writable by it, because the entrypoint writes config.js there.
COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 docker-entrypoint.d/10-write-config.sh /docker-entrypoint.d/10-write-config.sh

USER root
# Packages the base ships carry HIGH CVEs, and their fixes are pinned here
# until an nginx-unprivileged tag ships them; then each goes, and `make scan`
# shows it is safe to drop:
#   libexpat 2.8.4      CVE-2026-93990
#   pcre2 10.48         CVE-2026-103111
#   tiff 4.7.1          CVE-2026-4775
#   brotli-libs 1.2.0   CVE-2026-111497
#   curl, libcurl 8.22  CVE-2026-92392
#   libx11 1.8.13       CVE-2026-88806
# Alpine keeps only the newest build of a package, so a pin stops resolving
# when a newer one lands: libexpat moved from 2.8.5-r0 to 2.9.0-r0.
RUN apk add --no-cache libexpat=2.9.0-r0 pcre2=10.49-r0 tiff=4.7.2-r0 \
      brotli-libs=1.2.1-r0 curl=8.23.0-r0 libcurl=8.23.0-r0 libx11=1.8.14-r0 \
 && chown 101:101 /usr/share/nginx/html
USER 101

EXPOSE 8080
