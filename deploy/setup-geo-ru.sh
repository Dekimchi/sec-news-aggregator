#!/usr/bin/env bash
# Restrict public HTTP/HTTPS (80/443) to Russian IP ranges.
# SSH (22) stays open worldwide so CI/CD and admin access keep working.
set -euo pipefail

ZONE_DIR="${ZONE_DIR:-/var/lib/sec-news-geoip}"
V4_SET="sec-news-ru-ipv4"
V6_SET="sec-news-ru-ipv6"
V4_URL="${GEOIP_RU_V4_URL:-https://www.ipdeny.com/ipblocks/data/aggregated/ru-aggregated.zone}"
V6_URL="${GEOIP_RU_V6_URL:-https://www.ipdeny.com/ipv6/ipaddresses/aggregated/ru-aggregated.zone}"
COMMENT_ALLOW="sec-news-geo-ru-allow"
COMMENT_DROP="sec-news-geo-ru-drop"
COMMENT_LO="sec-news-geo-ru-lo"

export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq ipset iptables curl

mkdir -p "$ZONE_DIR"
tmp_v4="$(mktemp)"
tmp_v6="$(mktemp)"
cleanup() { rm -f "$tmp_v4" "$tmp_v6"; }
trap cleanup EXIT

fetch_zone() {
  local url="$1" out="$2"
  # ipdeny sometimes breaks HTTP/2; force HTTP/1.1 and retry once.
  curl --http1.1 -fsSL --retry 2 --retry-delay 2 --max-time 60 -o "$out" "$url"
}

if ! fetch_zone "$V4_URL" "$tmp_v4"; then
  if [ -s "$ZONE_DIR/ru-ipv4.zone" ]; then
    echo "WARN: failed to refresh RU IPv4 zone; reusing cached file" >&2
    cp "$ZONE_DIR/ru-ipv4.zone" "$tmp_v4"
  else
    echo "Failed to download RU IPv4 zone and no cache exists" >&2
    exit 1
  fi
fi

# IPv6 list is optional — empty/missing file just skips v6 rules.
if ! fetch_zone "$V6_URL" "$tmp_v6"; then
  if [ -s "$ZONE_DIR/ru-ipv6.zone" ]; then
    cp "$ZONE_DIR/ru-ipv6.zone" "$tmp_v6"
  else
    : >"$tmp_v6"
  fi
fi

# Basic sanity: zone must contain at least a few CIDRs.
v4_count="$(grep -E '^[0-9]' "$tmp_v4" | wc -l | tr -d ' ')"
if [ "${v4_count:-0}" -lt 10 ]; then
  echo "Refusing to apply geo rules: RU IPv4 zone looks empty ($v4_count entries)" >&2
  exit 1
fi

mv "$tmp_v4" "$ZONE_DIR/ru-ipv4.zone"
mv "$tmp_v6" "$ZONE_DIR/ru-ipv6.zone"
trap - EXIT

ipset create "$V4_SET" hash:net family inet maxelem 262144 -exist
ipset flush "$V4_SET"
while IFS= read -r cidr; do
  case "$cidr" in
    ''|\#*) continue ;;
  esac
  ipset add "$V4_SET" "$cidr" -exist
done <"$ZONE_DIR/ru-ipv4.zone"

ipset create "$V6_SET" hash:net family inet6 maxelem 262144 -exist
ipset flush "$V6_SET"
if [ -s "$ZONE_DIR/ru-ipv6.zone" ]; then
  while IFS= read -r cidr; do
    case "$cidr" in
      ''|\#*) continue ;;
    esac
    ipset add "$V6_SET" "$cidr" -exist
  done <"$ZONE_DIR/ru-ipv6.zone"
fi

# Prefer UFW chain so rules survive `ufw reload`; fall back to INPUT.
v4_chain="INPUT"
if iptables -L ufw-before-input -n >/dev/null 2>&1; then
  v4_chain="ufw-before-input"
fi

while iptables -D "$v4_chain" -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_DROP" -j DROP 2>/dev/null; do :; done
while iptables -D "$v4_chain" -p tcp -m multiport --dports 80,443 -m set --match-set "$V4_SET" src -m comment --comment "$COMMENT_ALLOW" -j ACCEPT 2>/dev/null; do :; done
while iptables -D "$v4_chain" -i lo -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_LO" -j ACCEPT 2>/dev/null; do :; done
# Also clear legacy INPUT copies from older deploys.
while iptables -D INPUT -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_DROP" -j DROP 2>/dev/null; do :; done
while iptables -D INPUT -p tcp -m multiport --dports 80,443 -m set --match-set "$V4_SET" src -m comment --comment "$COMMENT_ALLOW" -j ACCEPT 2>/dev/null; do :; done
while iptables -D INPUT -i lo -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_LO" -j ACCEPT 2>/dev/null; do :; done

iptables -I "$v4_chain" 1 -i lo -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_LO" -j ACCEPT
iptables -I "$v4_chain" 2 -p tcp -m multiport --dports 80,443 -m set --match-set "$V4_SET" src -m comment --comment "$COMMENT_ALLOW" -j ACCEPT
iptables -I "$v4_chain" 3 -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_DROP" -j DROP

if command -v ip6tables >/dev/null 2>&1; then
  v6_chain="INPUT"
  if ip6tables -L ufw6-before-input -n >/dev/null 2>&1; then
    v6_chain="ufw6-before-input"
  fi

  while ip6tables -D "$v6_chain" -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_DROP" -j DROP 2>/dev/null; do :; done
  while ip6tables -D "$v6_chain" -p tcp -m multiport --dports 80,443 -m set --match-set "$V6_SET" src -m comment --comment "$COMMENT_ALLOW" -j ACCEPT 2>/dev/null; do :; done
  while ip6tables -D "$v6_chain" -i lo -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_LO" -j ACCEPT 2>/dev/null; do :; done
  while ip6tables -D INPUT -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_DROP" -j DROP 2>/dev/null; do :; done
  while ip6tables -D INPUT -p tcp -m multiport --dports 80,443 -m set --match-set "$V6_SET" src -m comment --comment "$COMMENT_ALLOW" -j ACCEPT 2>/dev/null; do :; done
  while ip6tables -D INPUT -i lo -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_LO" -j ACCEPT 2>/dev/null; do :; done

  ip6tables -I "$v6_chain" 1 -i lo -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_LO" -j ACCEPT
  v6_entries="$(ipset list "$V6_SET" | awk '/Number of entries/ {print $4}')"
  if [ "${v6_entries:-0}" -gt 0 ]; then
    ip6tables -I "$v6_chain" 2 -p tcp -m multiport --dports 80,443 -m set --match-set "$V6_SET" src -m comment --comment "$COMMENT_ALLOW" -j ACCEPT
    ip6tables -I "$v6_chain" 3 -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_DROP" -j DROP
  else
    # No RU IPv6 ranges loaded — block public IPv6 web access.
    ip6tables -I "$v6_chain" 2 -p tcp -m multiport --dports 80,443 -m comment --comment "$COMMENT_DROP" -j DROP
  fi
fi

mkdir -p /etc/ipset.d
ipset save "$V4_SET" >"/etc/ipset.d/${V4_SET}.set"
ipset save "$V6_SET" >"/etc/ipset.d/${V6_SET}.set" 2>/dev/null || true

echo "Geo-IP RU filter applied on :80/:443 (SSH unrestricted). IPv4 entries: $(ipset list "$V4_SET" | awk '/Number of entries/ {print $4}')"
