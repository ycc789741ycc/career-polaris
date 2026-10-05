#!/bin/sh
# Fails the start with what to set, rather than serving a site with no name:
# the hostname is what the certificate is for.
set -eu
if [ -z "${SITE_HOSTNAME:-}" ]; then
  echo "ERROR: SITE_HOSTNAME is required where the proxy runs (the site's name, e.g. 203.0.113.7.sslip.io)." >&2
  exit 1
fi
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
