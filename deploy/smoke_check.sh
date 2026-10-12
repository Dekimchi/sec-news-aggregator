#!/usr/bin/env bash
# Post-deploy smoke checks: service must be fully usable, not just "process started".
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/sec-news-aggregator}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
READY_URL="${READY_URL:-http://127.0.0.1:8000/ready}"
LOGIN_URL="${LOGIN_URL:-http://127.0.0.1:8000/login}"
HTTPS_HEALTH_URL="${HTTPS_HEALTH_URL:-https://127.0.0.1/health}"
HTTPS_READY_URL="${HTTPS_READY_URL:-https://127.0.0.1/ready}"
HTTPS_LOGIN_URL="${HTTPS_LOGIN_URL:-https://127.0.0.1/login}"

fail() {
  echo "SMOKE FAIL: $*" >&2
  systemctl --no-pager -l status sec-news || true
  journalctl -u sec-news -n 100 --no-pager || true
  exit 1
}

echo "=== smoke: systemd ==="
systemctl is-active --quiet sec-news || fail "sec-news is not active"
systemctl is-active --quiet caddy || fail "caddy is not active"

echo "=== smoke: wait for app ==="
ok=0
for _ in $(seq 1 30); do
  if curl -fsS "$HEALTH_URL" 2>/dev/null | grep -q '"ok":true'; then
    ok=1
    break
  fi
  sleep 1
done
[[ "$ok" -eq 1 ]] || fail "health endpoint did not become ready"

echo "=== smoke: /ready (templates + filters + scheduler) ==="
ready_body="$(curl -fsS "$READY_URL")" || fail "GET /ready failed"
echo "$ready_body" | grep -q '"ok":true' || fail "/ready not ok: $ready_body"
echo "$ready_body" | grep -q '"scheduler_running":true' || fail "scheduler is not running"

echo "=== smoke: /login renders ==="
login_code="$(curl -sS -o /tmp/sec-news-login.html -w '%{http_code}' "$LOGIN_URL")"
[[ "$login_code" == "200" ]] || fail "GET /login returned $login_code"
grep -q 'sec-news' /tmp/sec-news-login.html || fail "/login HTML missing brand"

echo "=== smoke: HTTPS via Caddy ==="
curl -fsSk "$HTTPS_HEALTH_URL" | grep -q '"ok":true' || fail "HTTPS /health failed"
curl -fsSk "$HTTPS_READY_URL" | grep -q '"ok":true' || fail "HTTPS /ready failed"
https_login="$(curl -skS -o /dev/null -w '%{http_code}' "$HTTPS_LOGIN_URL")"
[[ "$https_login" == "200" ]] || fail "HTTPS /login returned $https_login"

echo "=== smoke: HTTP→HTTPS redirect ==="
redir="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1/health || true)"
[[ "$redir" == "301" || "$redir" == "308" ]] || fail "expected HTTP redirect, got $redir"

echo "=== smoke: offline template compile ==="
cd "$APP_DIR"
# shellcheck disable=SC1091
. .venv/bin/activate
python - <<'PY'
from app.main import templates, _READY_TEMPLATES, _READY_FILTERS

missing = [n for n in _READY_FILTERS if n not in templates.env.filters]
if missing:
    raise SystemExit(f"missing filters: {missing}")
for name in _READY_TEMPLATES:
    templates.env.get_template(name)
print("templates_ok", len(_READY_TEMPLATES))
PY

echo "SMOKE OK"
