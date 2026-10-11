#!/usr/bin/env bash
# One-time setup on the VPS (run as a sudo-capable user).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sec-news-aggregator}"
REPO_URL="${REPO_URL:-https://github.com/Dekimchi/sec-news-aggregator.git}"
SERVICE_USER="${SERVICE_USER:-www-data}"

sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — edit APP_SECRET and BASIC_AUTH_PASSWORD before starting."
fi

sudo cp deploy/sec-news.service /etc/systemd/system/sec-news.service
sudo sed -i "s|/opt/sec-news-aggregator|$APP_DIR|g" /etc/systemd/system/sec-news.service
sudo sed -i "s|User=www-data|User=$SERVICE_USER|g" /etc/systemd/system/sec-news.service

# Allow the deploy user to restart the service without a password prompt.
DEPLOY_USER="${DEPLOY_USER:-$USER}"
echo "$DEPLOY_USER ALL=(root) NOPASSWD: /bin/systemctl restart sec-news, /bin/systemctl status sec-news" | sudo tee "/etc/sudoers.d/sec-news-deploy" >/dev/null
sudo chmod 440 "/etc/sudoers.d/sec-news-deploy"

sudo systemctl daemon-reload
sudo systemctl enable sec-news
sudo systemctl restart sec-news
sudo systemctl --no-pager status sec-news

echo "Bootstrap done. Put the CI deploy SSH public key into ~/.ssh/authorized_keys for $DEPLOY_USER."
