#!/usr/bin/env bash
# Idempotent reverse-proxy + firewall + fail2ban setup (no domain required).
# Usage:
#   bash deploy/setup-proxy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sec-news-aggregator}"
CERT_DIR="/etc/caddy/certs"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl ufw fail2ban gpg openssl

if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq caddy
fi

mkdir -p /var/log/caddy "$CERT_DIR"
chown -R caddy:caddy /var/log/caddy
chmod 755 /var/log/caddy

# Self-signed cert for IP access (no public domain).
if [ ! -f "$CERT_DIR/cert.pem" ] || [ ! -f "$CERT_DIR/key.pem" ]; then
  PUB_IP="$(curl -4 -fsS --max-time 5 ifconfig.me 2>/dev/null || true)"
  if [ -z "${PUB_IP}" ]; then
    PUB_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  SAN="IP:127.0.0.1,DNS:localhost"
  if [ -n "${PUB_IP}" ]; then
    SAN="${SAN},IP:${PUB_IP}"
  fi
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem" \
    -days 825 \
    -subj "/CN=${PUB_IP:-localhost}" \
    -addext "subjectAltName=${SAN}"
  chmod 640 "$CERT_DIR/key.pem"
  chmod 644 "$CERT_DIR/cert.pem"
  chown -R caddy:caddy "$CERT_DIR"
fi

install -m 644 "$APP_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
install -m 644 "$APP_DIR/deploy/fail2ban/sec-news-auth.conf" /etc/fail2ban/filter.d/sec-news-auth.conf
install -m 644 "$APP_DIR/deploy/fail2ban/sec-news-auth.local" /etc/fail2ban/jail.d/sec-news-auth.local
install -m 644 "$APP_DIR/deploy/sec-news-geoip.service" /etc/systemd/system/sec-news-geoip.service
install -m 644 "$APP_DIR/deploy/sec-news-geoip.timer" /etc/systemd/system/sec-news-geoip.timer
install -m 644 "$APP_DIR/deploy/sec-news-system-update.service" /etc/systemd/system/sec-news-system-update.service
install -m 644 "$APP_DIR/deploy/sec-news-system-update.timer" /etc/systemd/system/sec-news-system-update.timer
# Point the unit at the real app path (supports non-default DEPLOY_PATH).
sed -i "s|/opt/sec-news-aggregator|$APP_DIR|g" /etc/systemd/system/sec-news-geoip.service

# Firewall: SSH open worldwide; 80/443 open at UFW layer, then geo-filter drops non-RU.
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

systemctl daemon-reload
systemctl enable caddy fail2ban sec-news-geoip.service sec-news-geoip.timer \
  sec-news-system-update.timer >/dev/null
systemctl restart fail2ban
caddy validate --config /etc/caddy/Caddyfile
systemctl restart caddy
sleep 2
if ! systemctl --no-pager --quiet is-active caddy; then
  echo "Caddy failed to start:" >&2
  journalctl -u caddy -n 40 --no-pager >&2 || true
  exit 1
fi

chmod +x "$APP_DIR/deploy/setup-geo-ru.sh" "$APP_DIR/deploy/setup-system-updates.sh"
bash "$APP_DIR/deploy/setup-geo-ru.sh"
bash "$APP_DIR/deploy/setup-system-updates.sh"
systemctl start sec-news-geoip.timer
systemctl start sec-news-system-update.timer

echo "Proxy configured (no domain): HTTPS only at https://SERVER_IP/ (self-signed); HTTP redirects"
echo "Geo-IP: ports 80/443 limited to RU ranges; SSH remains unrestricted for CD/admin"
echo "Updates: unattended-upgrades + daily timer; Python deps via Dependabot PRs"
fail2ban-client status sec-news-auth >/dev/null 2>&1 && echo "fail2ban jail: sec-news-auth OK" || echo "fail2ban jail: check later"
