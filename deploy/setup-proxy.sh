#!/usr/bin/env bash
# Usage (on VPS as root):
#   SITE_ADDRESS=news.example.com bash deploy/setup-proxy.sh
set -euo pipefail

SITE_ADDRESS="${SITE_ADDRESS:-}"
APP_DIR="${APP_DIR:-/opt/sec-news-aggregator}"

if [ -z "$SITE_ADDRESS" ]; then
  echo "Set SITE_ADDRESS to your domain, e.g.:"
  echo "  SITE_ADDRESS=news.example.com bash deploy/setup-proxy.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl ufw fail2ban

# Caddy repo
if [ ! -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update
fi
apt-get install -y caddy

mkdir -p /var/log/caddy
chown caddy:caddy /var/log/caddy

# Caddyfile
cp "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
sed -i "s/{\$SITE_ADDRESS:example.com}/$SITE_ADDRESS/g" /etc/caddy/Caddyfile

# fail2ban filter/jail
cp "$APP_DIR/deploy/fail2ban/sec-news-auth.conf" /etc/fail2ban/filter.d/sec-news-auth.conf
cp "$APP_DIR/deploy/fail2ban/sec-news-auth.local" /etc/fail2ban/jail.d/sec-news-auth.local

# Firewall: SSH + HTTP/HTTPS only
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

systemctl enable --now fail2ban
systemctl restart fail2ban
systemctl enable --now caddy
systemctl restart caddy
systemctl restart sec-news

echo "Proxy ready: https://$SITE_ADDRESS"
echo "Check: curl -I https://$SITE_ADDRESS/health"
echo "fail2ban: fail2ban-client status sec-news-auth"
