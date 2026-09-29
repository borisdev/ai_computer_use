#!/usr/bin/env bash
# Put Bank B's brand on tenant B, or take it off again.
#
#   scripts/reskin_tenant_b.sh on    # colours + typeface change; locators drift
#   scripts/reskin_tenant_b.sh off   # back to stock -- REQUIRED before the live suite
#
# ⛔ `on` DELIBERATELY BREAKS tests/test_cross_tenant_live.py. That is the
# point of the experiment -- the adopted control map no longer matches, so
# `maps adopt` refuses and replay stops at the precondition. Leaving it on and
# then running the suite reads as two broken tests rather than as a result,
# which is exactly what happened the first time.
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  on)
    docker compose -f docker-compose.yml -f docker-compose.reskin.yml \
      --profile tenant-b up -d --force-recreate --wait parabank-b
    ;;
  off)
    docker compose --profile tenant-b up -d --force-recreate --wait parabank-b
    ;;
  *) echo "usage: $0 {on|off}" >&2; exit 2 ;;
esac

sleep 5
uv run interfaceai env reset --tenant-b >/dev/null
printf 'tenant B skin: '
curl -s http://localhost:8081/parabank/template.css | head -1
