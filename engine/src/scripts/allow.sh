#!/bin/bash
# ameyaDB-allow.sh -- who is this node allowed to reach?
#
#   ameyaDB-allow.sh <my_id> all    # everyone (also how you heal a partition)
#   ameyaDB-allow.sh <my_id> 12     # nodes 1 and 2 only
#   ameyaDB-allow.sh <my_id> none   # nobody (used by ameyaDB-crash.sh)
#
# every call REPLACES the rules, it is not a delta -- so nothing has to
# remember the previous peer set to work out what changed.
#
# all netfilter knowledge in this project lives in this one file. the crash
# script does not touch iptables, it calls this.
set -uo pipefail

ME=${1:?usage: ameyaDB-allow.sh <my_id> <all|none|digits>}
ALLOWED=${2:?usage: ameyaDB-allow.sh <my_id> <all|none|digits>}

CHAIN=AMEYADB
MESH=8080:8084
DOMAIN=ameyadb.internal
NUM_NODES=5

# our own chain, hooked into INPUT and OUTPUT once, so we can wipe our rules
# without touching anything else in the filter table.
iptables -N $CHAIN 2>/dev/null || true
iptables -C INPUT  -j $CHAIN 2>/dev/null || iptables -I INPUT  -j $CHAIN
iptables -C OUTPUT -j $CHAIN 2>/dev/null || iptables -I OUTPUT -j $CHAIN
iptables -F $CHAIN

[ "$ALLOWED" = all ] && exit 0

for i in $(seq 0 $((NUM_NODES - 1))); do
  [ "$i" = "$ME" ] && continue
  if [ "$ALLOWED" != none ] && printf '%s' "$ALLOWED" | grep -q "$i"; then
    continue
  fi

  ip=$(getent hosts "node-$i.$DOMAIN" | awk '{print $1; exit}')
  if [ -z "$ip" ]; then
    echo "!! could not resolve node-$i.$DOMAIN" >&2
    continue
  fi

  # DROP, never REJECT. REJECT answers with an RST or ICMP-unreachable, which
  # tells the peer "host is up, port shut" -- that is a refused connection,
  # not a partition. DROP is silence, which is what a partition looks like.
  #
  # four rules because this node plays both roles: it dials higher-numbered
  # peers (their listener is the DESTINATION port) and is dialed by lower ones
  # (our listener is the SOURCE port). and since the chain hangs off both
  # INPUT and OUTPUT, these block that peer in BOTH directions -- rules on
  # this node alone are enough, the peer needs no matching rule of its own.
  iptables -A $CHAIN -s "$ip" -p tcp --sport $MESH -j DROP
  iptables -A $CHAIN -s "$ip" -p tcp --dport $MESH -j DROP
  iptables -A $CHAIN -d "$ip" -p tcp --sport $MESH -j DROP
  iptables -A $CHAIN -d "$ip" -p tcp --dport $MESH -j DROP
done

exit 0