#!/usr/bin/env bash
# One-shot provisioning for the ESC member API on a fresh Ubuntu 24.04
# Lightsail instance (1 vCPU / 1GB). Run as root (sudo bash setup.sh).
# Idempotent — safe to re-run.
#
# Two-phase on first use:
#   1st run: generates the esc user's SSH key and prints it → add it as a
#            read-only Deploy Key on the GitHub repo → re-run.
#   2nd run: clones the repo and finishes provisioning.
#
# Prerequisites:
#   - DNS: api-member.earhousesongwritingclub.com -> this server's static IP
#     (Cloudflare: DNS-only / grey cloud)

set -euo pipefail

REPO_SSH_URL="${1:?usage: setup.sh git@github.com:<you>/esc-member-api.git}"

echo "== 1/8 prefer IPv4 for outbound (avoids dual-stack hangs) =="
if ! grep -q '^precedence ::ffff:0:0/96 100' /etc/gai.conf 2>/dev/null; then
  echo 'precedence ::ffff:0:0/96 100' >> /etc/gai.conf
fi

echo "== 2/8 swap (1GB insurance against OOM) =="
if ! swapon --show | grep -q swapfile; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 3/8 packages =="
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git sqlite3 \
  debian-keyring debian-archive-keyring apt-transport-https curl

# Caddy official repo
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy
fi

echo "== 4/8 app user + deploy key =="
id -u esc &>/dev/null || useradd -m -s /bin/bash esc
if [ ! -f /home/esc/.ssh/id_ed25519 ]; then
  sudo -u esc bash -c '
    mkdir -p ~/.ssh && chmod 700 ~/.ssh
    ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "esc-lightsail-deploy"
    ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null
  '
fi

echo "== 5/8 code =="
if [ ! -d /home/esc/member-api/.git ]; then
  if ! sudo -u esc git clone "$REPO_SSH_URL" /home/esc/member-api 2>/dev/null; then
    cat <<EOF

CLONE FAILED — the repo is private and GitHub doesn't know this server yet.
Add this public key as a READ-ONLY Deploy Key on the repo
(GitHub -> repo -> Settings -> Deploy keys -> Add deploy key):

$(cat /home/esc/.ssh/id_ed25519.pub)

Then re-run this script with the same argument.
EOF
    exit 1
  fi
fi

echo "== 6/8 python venv =="
sudo -u esc bash -c '
  cd /home/esc/member-api
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
'

echo "== 7/8 systemd unit =="
cp /home/esc/member-api/deploy/member-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable member-api

echo "== 8/8 caddy =="
cp /home/esc/member-api/deploy/Caddyfile /etc/caddy/Caddyfile
systemctl enable caddy

cat <<'EOF'

DONE. Remaining manual steps:
  1. Create /home/esc/member-api/.env (copy .env.example, fill production
     values — see DEPLOYMENT.md). Then:
       sudo chown esc:esc /home/esc/member-api/.env
       sudo chmod 600 /home/esc/member-api/.env
  2. sudo systemctl start member-api caddy
  3. Verify: curl https://api-member.earhousesongwritingclub.com/health
  4. CI/CD: create a deploy SSH keypair for GitHub Actions
     (see DEPLOYMENT.md "CI/CD" section).
EOF
