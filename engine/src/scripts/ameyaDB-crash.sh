#!/bin/bash
# ameyaDB-crash.sh -- simulate a hard crash, stay down, come back.
#
#   ameyaDB-crash.sh <my_id> [downtime_seconds]
#
# WHY THE FIREWALL GOES UP FIRST:
# a process that exits has its sockets closed by the kernel, which sends a FIN
# to every peer. peers then see a clean EOF and know instantly the node is
# gone. real crashes -- power loss, kernel panic, a cut link -- send nothing,
# and the peer has to fall back on its own election timeouts. that guessing is
# what raft has to get right, so the FIN has to be suppressed or the test does
# not exercise the interesting path.
#
# this file owns the lifecycle only. every iptables rule comes from
# ameyaDB-allow.sh.
set -uo pipefail

ME=${1:?usage: ameyaDB-crash.sh <my_id> [seconds]}
SECS=${2:-30}

ALLOW=/usr/local/bin/ameyaDB-allow.sh
SERVICE=ameyaDB

# ORDER IS THE WHOLE POINT: filter up first, process killed second. reverse
# these two and the FINs leave before the filter exists.
"$ALLOW" "$ME" none

# `systemctl stop`, not `kill`. the unit is Restart=always, so a plain kill is
# undone by systemd in RestartSec=1 and the node is back before the test can
# observe anything. an explicit stop is the one thing Restart=always does not
# override -- that is what makes the downtime controllable.
systemctl stop $SERVICE

sleep "$SECS"

"$ALLOW" "$ME" all
systemctl start $SERVICE