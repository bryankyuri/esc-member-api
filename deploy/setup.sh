#!/usr/bin/env bash
# One-shot provisioning for the ESC member API on a fresh Ubuntu 24.04
# Lightsail instance (1 vCPU / 1GB). Run as root (sudo bash setup.sh).
#
# Prerequisites:
#   - DNS: api-member.earhousesongwritingclub.com -> this server's static IP
#     (Cloudflare: DNS-only / grey cloud)
#   - The member-api repo pushed to GitHub (private is fine; use a deploy
#     key or HTTPS token when cloning)

set -euo pipefail

REPO_URL="${1:?usage: setup.sh <git-repo-url>}"

echo "== 1/6 swap (1GB insurance against OOM) =="
if ! swapon --show | grep -q swapfile; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 2/6 packages =="
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

echo "== 3/6 app user + code =="
id -u esc &>/dev/null || useradd -m -s /bin/bash esc
if [ ! -d /home/esc/member-api ]; then
  sudo -u esc git clone "$REPO_URL" /home/esc/member-api
fi

echo "== 4/6 python venv =="
sudo -u esc bash -c '
  cd /home/esc/member-api
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
'

echo "== 5/6 systemd unit =="
cp /home/esc/member-api/deploy/member-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable member-api

echo "== 6/6 caddy =="
cp /home/esc/member-api/deploy/Caddyfile /etc/caddy/Caddyfile
systemctl enable caddy

cat <<'EOF'

DONE. Remaining manual steps:
  1. Create /home/esc/member-api/.env (copy .env.example, fill production
     values — see DEPLOYMENT.md). Then:  chown esc:esc .env && chmod 600 .env
  2. systemctl start member-api caddy
  3. Verify: curl https://api-member.earhousesongwritingclub.com/health
EOF
