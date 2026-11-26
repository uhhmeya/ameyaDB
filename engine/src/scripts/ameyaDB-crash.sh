#!/bin/bash
set -uo pipefail

ME=${1:?usage: ameyaDB-crash.sh <my_id> [seconds]}
SECS=${2:-30}

ALLOW=/usr/local/bin/ameyaDB-allow.sh
SERVICE=ameyaDB

"$ALLOW" "$ME" none

timeout 1 bash -c "echo '{\"node\":$ME,\"type\":\"cut\",\"wall_us\":$(date +%s%6N)}' > /dev/tcp/10.0.100.70/9001" 2>/dev/null || true

systemctl stop $SERVICE

sleep "$SECS"

"$ALLOW" "$ME" all
systemctl start $SERVICE