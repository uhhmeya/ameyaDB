#!/usr/bin/env bash
#
# dooby.sh — bring the ameyaDB cluster up, run frontend + relay, and park
#            everything (stopped, not destroyed) on Ctrl-C.
#
#   ./dooby.sh           start stopped instances (fast, keeps disks + IPs)
#   ./dooby.sh --fresh   terraform-replace all 5 nodes (slow, clean slate)
#
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$ROOT_DIR/terraform"
BASTION_KEY="$HOME/.ssh/ameyaDB"
BASTION_REPO_DIR="ameyaDB"
AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION

# The bastion is a t3.micro (~$0.01/hr). Leaving it up avoids a 60s boot every
# run. Set to 1 if you also want it stopped on exit.
STOP_BASTION="${STOP_BASTION:-0}"

FRESH=0
[[ "${1:-}" == "--fresh" ]] && FRESH=1

NODE_IDS=""
BASTION_ID=""
BASTION_IP=""
FRONTEND_PID=""
RELAY_PID=""
CLEANED=0

say() { printf '\n\033[1m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31m!!\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- teardown --

kill_tree() {                      # kill a pid AND its descendants (portable)
  local pid="${1:-}" k
  [[ -z "$pid" ]] && return 0
  for k in $(pgrep -P "$pid" 2>/dev/null || true); do kill_tree "$k"; done
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  [[ "$CLEANED" == 1 ]] && return
  CLEANED=1
  echo ""
  say "shutting down"

  kill_tree "$FRONTEND_PID"
  kill_tree "$RELAY_PID"

  local to_stop="$NODE_IDS"
  [[ "$STOP_BASTION" == 1 ]] && to_stop="$to_stop $BASTION_ID"
  to_stop="$(echo "$to_stop" | xargs)"          # squeeze whitespace

  if [[ -n "$to_stop" ]]; then
    if aws ec2 stop-instances --instance-ids $to_stop >/dev/null; then
      echo "    stopped: $to_stop"
    else
      echo "    !! stop-instances FAILED — you are still being billed."
      echo "    !! run: aws ec2 stop-instances --instance-ids $to_stop"
    fi
  else
    echo "    !! no instance ids resolved — nothing stopped, check manually:"
    echo "    !! aws ec2 describe-instances --filters Name=tag:Name,Values='ameyaDB-*' \\"
    echo "    !!     Name=instance-state-name,Values=running \\"
    echo "    !!     --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==\`Name\`]|[0].Value]' --output text"
  fi

  echo "frontend, relay, & ec2s down"
  exit 0
}
trap cleanup INT TERM

# ---------------------------------------------------------------- discovery --

ids_by_name() {                    # tag-name glob -> space separated ids
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$1" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text \
  | tr '\t' ' ' | xargs
}

command -v aws >/dev/null       || die "aws cli not on PATH"
command -v terraform >/dev/null || die "terraform not on PATH"
[[ -f "$BASTION_KEY" ]]         || die "ssh key not found at $BASTION_KEY"

if [[ "$FRESH" == 1 ]]; then
  say "--fresh: replacing all 5 db nodes (this destroys their root disks)"
  terraform -chdir="$TF_DIR" apply -auto-approve \
    -replace='aws_instance.db_node[0]' \
    -replace='aws_instance.db_node[1]' \
    -replace='aws_instance.db_node[2]' \
    -replace='aws_instance.db_node[3]' \
    -replace='aws_instance.db_node[4]' || die "terraform apply failed"
else
  say "reconciling infra (no replacement)"
  terraform -chdir="$TF_DIR" apply -auto-approve || die "terraform apply failed"
fi

NODE_IDS="$(terraform -chdir="$TF_DIR" output -raw node_instance_ids 2>/dev/null | xargs)"
[[ -z "$NODE_IDS" ]] && NODE_IDS="$(ids_by_name 'ameyaDB-node-*')"
[[ -z "$NODE_IDS" ]] && die "could not resolve node instance ids"

BASTION_ID="$(terraform -chdir="$TF_DIR" output -raw bastion_instance_id 2>/dev/null | xargs)"
[[ -z "$BASTION_ID" ]] && BASTION_ID="$(ids_by_name 'ameyaDB-bastion')"
[[ -z "$BASTION_ID" ]] && die "could not resolve bastion instance id"

BASTION_IP="$(terraform -chdir="$TF_DIR" output -raw bastion_ip 2>/dev/null | xargs)"
[[ -z "$BASTION_IP" ]] && die "could not resolve bastion_ip"

echo "    nodes   : $NODE_IDS"
echo "    bastion : $BASTION_ID @ $BASTION_IP"

# ------------------------------------------------------------------ startup --

# Let any instances still stopping (from a previous Ctrl-C) finish first --
# start-instances rejects instances in transitional states.
SETTLING="$(aws ec2 describe-instances --instance-ids $BASTION_ID $NODE_IDS \
  --query 'Reservations[].Instances[?State.Name==`stopping`].InstanceId' \
  --output text | xargs)"
if [[ -n "$SETTLING" ]]; then
  say "waiting for stopping instances to settle: $SETTLING"
  aws ec2 wait instance-stopped --instance-ids $SETTLING
fi

say "starting instances"
# start-instances is a no-op on already-running instances, so this is safe.
if ! aws ec2 start-instances --instance-ids $BASTION_ID $NODE_IDS >/dev/null; then
  die "start-instances failed (see the error above).
     VcpuLimitExceeded means your On-Demand Standard vCPU quota is too low:
       aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A"
fi

say "waiting for bastion to pass status checks"
aws ec2 wait instance-status-ok --instance-ids "$BASTION_ID" \
  || die "bastion never became healthy"

say "waiting for all 5 nodes to pass status checks (not just 'running')"
aws ec2 wait instance-status-ok --instance-ids $NODE_IDS \
  || die "one or more nodes never became healthy"
echo "    ok: $(echo "$NODE_IDS" | wc -w | xargs) nodes healthy"

# ----------------------------------------------------------------- frontend --

say "starting frontend"
( cd "$ROOT_DIR/frontend" && exec npm run dev >/dev/null 2>&1 ) &
FRONTEND_PID=$!
echo "    http://localhost:5173"

# -------------------------------------------------------------------- relay --

ssh_bastion() {
  ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -i "$BASTION_KEY" "ec2-user@$BASTION_IP" "$@"
}

say "waiting for bastion sshd"
SSH_OK=0
for i in $(seq 1 40); do
  if ssh_bastion true 2>/dev/null; then SSH_OK=1; break; fi
  printf '\r    attempt %2d/40 ...' "$i"
done
echo ""
if [[ "$SSH_OK" != 1 ]]; then
  echo "    ssh never came up. last error was:"
  ssh_bastion true || true          # stderr NOT swallowed — read this
  cleanup
fi

# kill any relay left over from a previous run
ssh_bastion "pkill -f relay.py" >/dev/null 2>&1 && echo "    cleared zombie relay"

say "starting relay"
(
  ssh -tt -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -i "$BASTION_KEY" "ec2-user@$BASTION_IP" \
      "cd $BASTION_REPO_DIR && git pull --quiet && exec python3 -u relay.py"
  echo ""
  echo "    !! relay exited (code $?) — see the output above for why"
) &
RELAY_PID=$!
echo "    relay launched on $BASTION_IP:8765"
echo ""
echo "ctrl-C to stop"

# Block without spinning. `wait` is interruptible by the trap.
while kill -0 "$FRONTEND_PID" 2>/dev/null || kill -0 "$RELAY_PID" 2>/dev/null; do
  sleep 1
done
cleanup