#!/bin/bash
set -uo pipefail

ME=${1:?usage: ameyaDB-allow.sh <my_id> <all|none|digits>}
ALLOWED=${2:?usage: ameyaDB-allow.sh <my_id> <all|none|digits>}

RULE_LIST=AMEYADB
MESH=8080:8084
DOMAIN=ameyadb.internal
NUM_NODES=5

iptables -N $RULE_LIST 2>/dev/null || true
iptables -C INPUT  -j $RULE_LIST 2>/dev/null || iptables -I INPUT  -j $RULE_LIST
iptables -C OUTPUT -j $RULE_LIST 2>/dev/null || iptables -I OUTPUT -j $RULE_LIST

if [ "$ALLOWED" = all ]; then
  iptables -F $RULE_LIST
  exit 0
fi

RULES=""
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

  RULES+="-A $RULE_LIST -s $ip -p tcp --sport $MESH -j DROP"$'\n'
  RULES+="-A $RULE_LIST -s $ip -p tcp --dport $MESH -j DROP"$'\n'
  RULES+="-A $RULE_LIST -d $ip -p tcp --sport $MESH -j DROP"$'\n'
  RULES+="-A $RULE_LIST -d $ip -p tcp --dport $MESH -j DROP"$'\n'
done

printf '*filter\n:%s - [0:0]\n%sCOMMIT\n' "$RULE_LIST" "$RULES" | iptables-restore --noflush

exit 0