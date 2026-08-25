#!/bin/bash

set -e

BASTION_IP="107.20.154.53"
BASTION_KEY="$HOME/.ssh/ameyaDB"
BASTION_REPO_DIR="ameyaDB"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTANCE_IDS="i-0e6e669af96efd2b2 i-0ea00101be6dbf85e i-00e230837bd125239 i-01230f1eda1eb34cb i-08625a93638fdff86 i-014ca2f3dc3ba70b5"

SSH_RETRIES=10
SSH_RETRY_DELAY=3

cleanup() {
    kill "$FRONTEND_PID" "$RELAY_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" "$RELAY_PID" 2>/dev/null || true
    aws ec2 stop-instances --instance-ids $INSTANCE_IDS >/dev/null || true
    echo "frontend, relay, & ec2s down"
    exit 0
}
trap cleanup INT TERM

# clear zombie relay
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    -i "$BASTION_KEY" "ec2-user@$BASTION_IP" \
    "pkill -f relay.py" || true
echo "cleared zombie relay on bastion"

# start ec2s
aws ec2 start-instances --instance-ids $INSTANCE_IDS >/dev/null
aws ec2 wait instance-running --instance-ids $INSTANCE_IDS
echo "EC2s up"

# start frontend
(cd "$ROOT_DIR/frontend" && npm run dev) &
FRONTEND_PID=$!
echo "frontend up ~ http://localhost:5173"

# start relay
for i in $(seq 1 $SSH_RETRIES); do
    if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
            -i "$BASTION_KEY" "ec2-user@$BASTION_IP" \
            "cd $BASTION_REPO_DIR && git pull && python3 relay.py"; then
        break
    fi
    echo "relay ssh not ready yet, retrying ($i/$SSH_RETRIES)..."
    sleep $SSH_RETRY_DELAY
done &
RELAY_PID=$!
echo "relay up"
echo "ctrl-C to stop"

while true; do
    wait -n 2>/dev/null || true
done
