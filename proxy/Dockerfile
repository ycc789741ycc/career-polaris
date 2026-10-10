# The edge proxy (ADR 0053): TLS, one origin for the SPA and the api, and the
# per-address limits the app cannot see. Runs only on the droplet
# (deploy/droplet-1vcpu-2gb/); development and CI reach api and web directly.
#
# Caddy itself, plus one plugin, so it is built rather than pulled. Both are
# pinned: the Caddy version on the builder and the release it builds, and the
# rate-limit plugin by commit, since its last tag predates the Caddy it builds
# against.

FROM caddy:2.11.6-builder-alpine AS build
# The builder ships Go 1.27.1, whose standard library carries CVE-2026-78667
# (HIGH, net/http). Go fetches the pinned 1.27.2 toolchain for the build; drop
# this once a builder tag ships 1.27.2 or later, which `make scan` shows.
ENV GOTOOLCHAIN=go1.27.2
# Caddy 2.11.6 requires golang.org/x/net v0.59.0, which carries CVE-2026-78669
# (HIGH, HTTP/2 SETTINGS flood); the replace builds v0.60.0 instead. Drop it
# once a Caddy release requires 0.60.0 or later, which `make scan` shows.
RUN xcaddy build v2.11.6 \
      --with github.com/mholt/caddy-ratelimit@5625512f24f6f59d6f64fb3aafe5eecff0b286db \
      --replace golang.org/x/net=golang.org/x/net@v0.60.0 \
 # The builder gives the binary a file capability to bind ports below 1024.
 # Under no-new-privileges such a binary cannot even be executed, so it is
 # copied without one; the sysctl in compose opens the ports instead.
 && cat /usr/bin/caddy > /caddy && chmod 0755 /caddy

# The one stage: there is no dev or test variant of a proxy. Its Caddyfile is
# checked by `make lint`, with this image.
FROM caddy:2.11.6-alpine AS prod
COPY --from=build /caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
COPY start.sh /usr/local/bin/start-proxy
# Not root. Ports 80 and 443 are opened by the unprivileged-port sysctl compose
# sets, not by a capability, which no-new-privileges would refuse anyway.
RUN addgroup -S -g 10001 proxy \
 && adduser -S -D -H -u 10001 -G proxy proxy \
 && mkdir -p /data/caddy /config/caddy \
 && chown -R proxy:proxy /data /config \
 && chmod 0555 /usr/local/bin/start-proxy
USER proxy
CMD ["/usr/local/bin/start-proxy"]
