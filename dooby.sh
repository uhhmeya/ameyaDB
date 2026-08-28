#!/usr/bin/env bash
# dooby.sh — bring ameyaDB up (frontend + relay + nodes), stop instances on ctrl-C.
#   ./dooby.sh           start stopped instances (fast, keeps disks + IPs)
#   ./dooby.sh --fresh   terraform-replace all 5 nodes (slow, clean slate)
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$ROOT_DIR/terraform"
KEY="$HOME/.ssh/ameyaDB"
REPO="ameyaDB"
export AWS_REGION="${AWS_REGION:-us-east-1}"
STOP_BASTION="${STOP_BASTION:-0}"   # 1 = also stop the bastion (t3.micro) on exit

FRESH=0; [[ "${1:-}" == "--fresh" ]] && FRESH=1
NODE_IDS=""; BASTION_ID=""; BASTION_IP=""
FRONTEND_PID=""; RELAY_PID=""; CLEANED=0
RELAY_LOG="$(mktemp)"

die() { printf '!! %s\n' "$*" >&2; exit 1; }

kill_tree() {   # kill a pid and its descendants
  local pid="${1:-}" k
  [[ -z "$pid" ]] && return 0
  for k in $(pgrep -P "$pid" 2>/dev/null || true); do kill_tree "$k"; done
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  [[ "$CLEANED" == 1 ]] && return; CLEANED=1
  echo ""
  kill_tree "$FRONTEND_PID"; kill_tree "$RELAY_PID"; rm -f "$RELAY_LOG"
  local ids="$NODE_IDS"
  [[ "$STOP_BASTION" == 1 ]] && ids="$ids $BASTION_ID"
  ids="$(echo "$ids" | xargs)"
  if [[ -z "$ids" ]]; then
    echo "!! no instance ids resolved — nothing stopped, check the AWS console"
  elif aws ec2 stop-instances --instance-ids $ids >/dev/null; then
    echo "stopped: $ids"
  else
    echo "!! stop-instances FAILED — still billing. run: aws ec2 stop-instances --instance-ids $ids"
  fi
  exit 0
}
trap cleanup INT TERM
fail() { echo "!! $*"; cleanup; }

ids_by_name() {   # tag glob -> instance ids (fallback when terraform output is empty)
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$1" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text | tr '\t' ' ' | xargs
}
tf_out() { terraform -chdir="$TF_DIR" output -raw "$1" 2>/dev/null | xargs; }
settle() {   # start-instances rejects instances still 'stopping' from a previous run
  local s; s="$(aws ec2 describe-instances --instance-ids "$@" \
    --query 'Reservations[].Instances[?State.Name==`stopping`].InstanceId' --output text | xargs)"
  [[ -n "$s" ]] && aws ec2 wait instance-stopped --instance-ids $s
  return 0
}
ssh_bastion() {
  ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -i "$KEY" "ec2-user@$BASTION_IP" "$@"
}

command -v aws >/dev/null || die "aws cli not on PATH"
command -v terraform >/dev/null || die "terraform not on PATH"
[[ -f "$KEY" ]] || die "ssh key not found at $KEY"

echo "refreshing infrastructure..."
APPLY=(-auto-approve)
[[ "$FRESH" == 1 ]] && for i in 0 1 2 3 4; do APPLY+=("-replace=aws_instance.db_node[$i]"); done
TF_LOG_FILE="$(mktemp)"
terraform -chdir="$TF_DIR" apply "${APPLY[@]}" >"$TF_LOG_FILE" 2>&1 \
  || { cat "$TF_LOG_FILE"; rm -f "$TF_LOG_FILE"; die "terraform apply failed"; }
rm -f "$TF_LOG_FILE"

NODE_IDS="$(tf_out node_instance_ids)"
[[ -z "$NODE_IDS" ]] && NODE_IDS="$(ids_by_name 'ameyaDB-node-*')"
[[ -z "$NODE_IDS" ]] && die "could not resolve node instance ids"
BASTION_ID="$(tf_out bastion_instance_id)"
[[ -z "$BASTION_ID" ]] && BASTION_ID="$(ids_by_name 'ameyaDB-bastion')"
[[ -z "$BASTION_ID" ]] && die "could not resolve bastion instance id"
BASTION_IP="$(tf_out bastion_ip)"
[[ -z "$BASTION_IP" ]] && die "could not resolve bastion_ip"

echo "starting frontend..."
( cd "$ROOT_DIR/frontend" && exec npm run dev >/dev/null 2>&1 ) &
FRONTEND_PID=$!
echo "(http://localhost:5173) open this link then type ctrlA in console"

# order matters: relay.py keeps port 9000 closed until the browser attaches,
# and nodes only start after that — a node can never reach a browserless relay.
echo "starting relay..."
settle $BASTION_ID
aws ec2 start-instances --instance-ids $BASTION_ID >/dev/null || fail "start-instances (bastion) failed"
aws ec2 wait instance-status-ok --instance-ids $BASTION_ID || fail "bastion never became healthy"
for i in $(seq 1 40); do
  ssh_bastion true 2>/dev/null && break
  [[ "$i" == 40 ]] && { ssh_bastion true; fail "bastion sshd never came up"; }
  sleep 2
done
ssh_bastion "pkill -f relay.py" >/dev/null 2>&1
(
  ssh -tt -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -i "$KEY" "ec2-user@$BASTION_IP" "cd $REPO && git pull --quiet && exec python3 -u relay.py"
  rc=$?; echo "!! relay exited (code $rc)"
) > >(tee "$RELAY_LOG") 2>&1 &
RELAY_PID=$!

until grep -q "relay & browser are connected" "$RELAY_LOG"; do   # pause until browser is in
  kill -0 "$RELAY_PID" 2>/dev/null \
    || fail "relay died before the browser connected — is the bastion's relay.py up to date? (dooby git-pulls on the bastion)"
  sleep 1
done

echo "starting nodes..."
settle $NODE_IDS
aws ec2 start-instances --instance-ids $NODE_IDS >/dev/null \
  || fail "start-instances (nodes) failed — VcpuLimitExceeded means vCPU quota is too low"
IPS="$(terraform -chdir="$TF_DIR" output -json node_ips 2>/dev/null | tr -d '[]",' | xargs)"
[[ -z "$IPS" ]] && IPS="$(aws ec2 describe-instances --instance-ids $NODE_IDS \
  --query 'Reservations[].Instances[].PrivateIpAddress' --output text | xargs)"
echo "node_ips = $IPS"
aws ec2 wait instance-status-ok --instance-ids $NODE_IDS || fail "one or more nodes never became healthy"

while kill -0 "$FRONTEND_PID" 2>/dev/null || kill -0 "$RELAY_PID" 2>/dev/null; do sleep 1; done
cleanup