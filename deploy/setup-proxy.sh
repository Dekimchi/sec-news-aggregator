#!/usr/bin/env bash
# Idempotent reverse-proxy + firewall + fail2ban setup (no domain required).
# Usage:
#   bash deploy/setup-proxy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sec-news-aggregator}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl ufw fail2ban gpg

if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
fi

mkdir -p /var/log/caddy
touch /var/log/caddy/sec-news-access.log || true
chown -R caddy:caddy /var/log/caddy
chmod 755 /var/log/caddy

install -m 644 "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
install -m 644 "$APP_DIR/deploy/fail2ban/sec-news-auth.conf" /etc/fail2ban/filter.d/sec-news-auth.conf
install -m 644 "$APP_DIR/deploy/fail2ban/sec-news-auth.local" /etc/fail2ban/jail.d/sec-news-auth.local

# Firewall: SSH + HTTP/HTTPS
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

systemctl enable caddy fail2ban >/dev/null
systemctl restart fail2ban
caddy validate --config /etc/caddy/Caddyfile
systemctl restart caddy
sleep 2
if ! systemctl --no-pager --quiet is-active caddy; then
  echo "Caddy failed to start:" >&2
  journalctl -u caddy -n 40 --no-pager >&2 || true
  exit 1
fi

echo "Proxy configured (no domain): http://SERVER_IP/ and https://SERVER_IP/ (self-signed)"
fail2ban-client status sec-news-auth >/dev/null 2>&1 && echo "fail2ban jail: sec-news-auth OK" || echo "fail2ban jail: check later"
