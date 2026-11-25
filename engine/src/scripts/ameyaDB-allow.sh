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

# make sure message is valid
ME=${1:?usage: ameyaDB-allow.sh <my_id> <all|none|digits>}
ALLOWED=${2:?usage: ameyaDB-allow.sh <my_id> <all|none|digits>}

# config
RULE_LIST=AMEYADB
MESH=8080:8084
DOMAIN=ameyadb.internal
NUM_NODES=5

# creates ameyaDB rule list
iptables -N $RULE_LIST 2>/dev/null || true
iptables -C INPUT  -j $RULE_LIST 2>/dev/null || iptables -I INPUT  -j $RULE_LIST
iptables -C OUTPUT -j $RULE_LIST 2>/dev/null || iptables -I OUTPUT -j $RULE_LIST

# everyone is allowed
if [ "$ALLOWED" = all ]; then
  iptables -F $RULE_LIST
  exit 0
fi

# work out every rule first, the firewall is not touched yet
RULES=""
for i in $(seq 0 $((NUM_NODES - 1))); do
  [ "$i" = "$ME" ] && continue
  if [ "$ALLOWED" != none ] && printf '%s' "$ALLOWED" | grep -q "$i"; then
    continue
  fi

  # grabs ports+ips of other nodes
  ip=$(getent hosts "node-$i.$DOMAIN" | awk '{print $1; exit}')
  if [ -z "$ip" ]; then
    echo "!! could not resolve node-$i.$DOMAIN" >&2
    continue
  fi

  # don't allow connections denied nodes
  RULES+="-A $RULE_LIST -s $ip -p tcp --sport $MESH -j DROP"$'\n'
  RULES+="-A $RULE_LIST -s $ip -p tcp --dport $MESH -j DROP"$'\n'
  RULES+="-A $RULE_LIST -d $ip -p tcp --sport $MESH -j DROP"$'\n'
  RULES+="-A $RULE_LIST -d $ip -p tcp --dport $MESH -j DROP"$'\n'
done

# swap the whole rule list in one shot. every cut lands at the same instant, and going
# from one partition to another never opens a gap where everyone is allowed
printf '*filter\n:%s - [0:0]\n%sCOMMIT\n' "$RULE_LIST" "$RULES" | iptables-restore --noflush

exit 0