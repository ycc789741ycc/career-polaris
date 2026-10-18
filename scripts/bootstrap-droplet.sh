#!/usr/bin/env bash
# Prepares a fresh Ubuntu droplet to run CareerPolaris (docs/deploy.md, section
# 2): SSH by key only, automatic security updates, 1 GB of swap for the host,
# Docker Engine with the compose plugin, make and git, and the `deploy` user
# the compute machine rolls releases out as (ADR 0081).
#
# DEPLOY_SSH_PUBLIC_KEY, if set, is the compute machine's rollout key (the .pub
# of its ROLLOUT_SSH_KEY). It is accepted only from the tailnet's addresses,
# so only through the tunnel. Without it the user is made with no key.
#
# Run it as root, either way:
#   - pasted as the droplet's User data when creating it, so it has run before
#     anyone can log in (its output is in /var/log/cloud-init-output.log);
#   - or on a droplet that already exists: clone the repository, then
#     `sudo scripts/bootstrap-droplet.sh`.
# Running it again changes nothing that is already in place.
#
# A host script, not a make target in a container, because it installs Docker
# and make themselves: there is nothing yet to run a container with. It holds
# no secret and starts nothing. .env, release.env and the registry login stay
# by hand, as docs/deploy.md says, because User data is kept by DigitalOcean
# and readable by any process on the droplet.
set -euo pipefail

# The Ubuntu LTS releases this has been written for. Docker's apt repository
# serves both.
SUPPORTED_UBUNTU="24.04 26.04"
SWAP_FILE=/swapfile
SWAP_SIZE=1G
DEPLOY_USER=deploy
CHECKOUT=/srv/careerpolaris
# Tailscale's addresses: the rollout key works only through the tunnel.
TAILNET_RANGE=100.64.0.0/10

say() { echo "bootstrap: $*"; }
fail() { echo "bootstrap: ERROR: $*" >&2; exit 1; }

# --- Check everything first, so a refusal leaves the machine untouched --------

[ "$(id -u)" -eq 0 ] || fail "run as root (sudo $0)."

# shellcheck source=/dev/null
. /etc/os-release
[ "${ID:-}" = ubuntu ] || fail "this is ${ID:-an unknown system}, not Ubuntu."
case " $SUPPORTED_UBUNTU " in
  *" ${VERSION_ID:-} "*) ;;
  *) fail "Ubuntu ${VERSION_ID:-?} is not one of: $SUPPORTED_UBUNTU." ;;
esac

# Turning passwords off with no key to log in with would lock everyone out.
key_count="$(cat /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys 2>/dev/null \
  | grep -cE '^(ssh-|ecdsa-|sk-)' || true)"
[ "$key_count" -gt 0 ] || fail "no SSH key in any authorized_keys; add one before passwords go."

if [ -n "${DEPLOY_SSH_PUBLIC_KEY:-}" ]; then
  [[ "$DEPLOY_SSH_PUBLIC_KEY" =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9-]+)\ [A-Za-z0-9+/=]+(\ .*)?$ ]] \
    || fail "DEPLOY_SSH_PUBLIC_KEY is not one public key line (ssh-ed25519 AAAA... comment)."
fi

export DEBIAN_FRONTEND=noninteractive

# --- SSH: keys only ------------------------------------------------------------

# 10- sorts before cloud-init's 50-cloud-init.conf, and sshd keeps the first
# value it reads, so this wins over a `PasswordAuthentication yes` there.
ssh_conf=/etc/ssh/sshd_config.d/10-careerpolaris.conf
cat > "$ssh_conf.new" <<'EOF'
# Written by scripts/bootstrap-droplet.sh: SSH keys only.
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
if cmp -s "$ssh_conf.new" "$ssh_conf"; then
  rm "$ssh_conf.new"
else
  mv "$ssh_conf.new" "$ssh_conf"
  sshd -t || { rm -f "$ssh_conf"; fail "sshd rejected $ssh_conf; removed it, nothing changed."; }
  # Since 24.04 sshd may be socket-activated and not running yet; it reads this
  # when it starts, so reload only one that runs.
  systemctl try-reload-or-restart ssh
  say "SSH now takes keys only."
fi
[ "$(sshd -T | awk '$1 == "passwordauthentication" { print $2 }')" = no ] \
  || fail "sshd still accepts passwords: another file in /etc/ssh/sshd_config.d sets it first."

# --- Automatic security updates -------------------------------------------------

apt-get update -q
apt-get install -y -q unattended-upgrades ca-certificates curl make git
# What `dpkg-reconfigure unattended-upgrades` writes when you answer yes: look
# for updates daily and install the security ones. It never reboots; see
# /var/run/reboot-required.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades >/dev/null
say "security updates install daily."

# --- Swap, for the host only ------------------------------------------------------

# Containers set memswap_limit to mem_limit, so this never hides a container
# that overruns; it spares dockerd, sshd and apt the OOM killer.
if ! grep -q "^$SWAP_FILE " /proc/swaps; then
  if [ ! -f "$SWAP_FILE" ]; then
    fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
    chmod 600 "$SWAP_FILE"
    mkswap "$SWAP_FILE" >/dev/null
  fi
  swapon "$SWAP_FILE"
  say "swap on: $SWAP_SIZE at $SWAP_FILE."
fi
grep -q "^$SWAP_FILE " /etc/fstab || echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab

# --- Docker Engine, from Docker's own repository ----------------------------------

# Not pinned to a version: security fixes should arrive with apt. Docker's
# repository is not one unattended-upgrades follows, so `apt-get upgrade` it
# now and then.
install -m 0755 -d /etc/apt/keyrings
if [ ! -s /etc/apt/keyrings/docker.asc ]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker >/dev/null

# --- The rollout's user (ADR 0081) -------------------------------------------------

# The compute machine deploys each release as this user, over SSH through the
# tunnel: `make` in the checkout, which it owns. The docker group is root on
# this host in effect; that is what deploying needs, and the key below is
# accepted only from the tailnet.
id -u "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"
if [ -n "${DEPLOY_SSH_PUBLIC_KEY:-}" ]; then
  install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh"
  echo "from=\"${TAILNET_RANGE}\",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ${DEPLOY_SSH_PUBLIC_KEY}" \
    > "/home/${DEPLOY_USER}/.ssh/authorized_keys"
  chown "$DEPLOY_USER:$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh/authorized_keys"
  chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys"
  say "${DEPLOY_USER} accepts the rollout key from ${TAILNET_RANGE} only."
fi
if [ -d "$CHECKOUT" ]; then
  chown -R "$DEPLOY_USER:$DEPLOY_USER" "$CHECKOUT"
  say "${CHECKOUT} belongs to ${DEPLOY_USER}."
fi

say "done on Ubuntu $VERSION_ID:"
say "  $(docker --version)"
say "  $(docker compose version)"
say "  $(make --version | head -1)"
say "  swap: $(swapon --show=NAME,SIZE --noheadings | awk -v f="$SWAP_FILE" '$1 == f { print $2 }')"
say "next: docs/deploy.md, section 2 — the repository, .env, then make."
