#!/usr/bin/env bash

if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

set -uo pipefail

{

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$ROOT_DIR/terraform"
SSH_KEY_PATH="$HOME/.ssh/ameyaDB"
REPO_NAME_ON_BASTION="ameyaDB"
export AWS_REGION="${AWS_REGION:-us-east-1}"

TERRAFORM_FLAGS_THAT_REMOVE_NAT="-var nat_enabled=false -target=aws_route_table.private -target=aws_nat_gateway.geochron -target=aws_eip.nat"

REPLACE_ALL_NODES=0
NODE_INSTANCE_IDS=""
BASTION_INSTANCE_ID=""
BASTION_IP=""
FRONTEND_PID=""
RELAY_PID=""
ALREADY_SHUT_DOWN=0
NAT_GATEWAY_MAY_EXIST=0
RELAY_LOG_FILE="$(mktemp)"

exit_with_error_message() {
  printf '!! %s\n' "$*" >&2
  ALREADY_SHUT_DOWN=1
  remove_nat_gateway_to_stop_billing
  exit 1
}

remove_nat_gateway_to_stop_billing() {
  [[ "$NAT_GATEWAY_MAY_EXIST" == 1 ]] || return 0
  NAT_GATEWAY_MAY_EXIST=0
  echo "removing NAT gateway + EIP (~1 min, let it finish)..."
  local terraform_output_file; terraform_output_file="$(mktemp)"
  if terraform -chdir="$TF_DIR" apply -auto-approve -input=false $TERRAFORM_FLAGS_THAT_REMOVE_NAT >"$terraform_output_file" 2>&1; then
    echo "NAT gateway removed"
  else
    cat "$terraform_output_file"
    echo "!! NAT teardown FAILED — still billing. run: terraform -chdir=$TF_DIR apply $TERRAFORM_FLAGS_THAT_REMOVE_NAT"
  fi
  rm -f "$terraform_output_file"
}

stop_process_and_all_its_children() {
  local process_id="${1:-}" child_process_id
  [[ -z "$process_id" ]] && return 0
  for child_process_id in $(pgrep -P "$process_id" 2>/dev/null || true); do
    stop_process_and_all_its_children "$child_process_id"
  done
  kill "$process_id" 2>/dev/null || true
}

shut_everything_down_and_exit() {
  [[ "$ALREADY_SHUT_DOWN" == 1 ]] && return; ALREADY_SHUT_DOWN=1
  echo ""

  stop_process_and_all_its_children "$FRONTEND_PID"
  stop_process_and_all_its_children "$RELAY_PID"
  rm -f "$RELAY_LOG_FILE"

  local all_instance_ids="$(echo "$NODE_INSTANCE_IDS $BASTION_INSTANCE_ID" | xargs)"
  if [[ -z "$all_instance_ids" ]]; then
    echo "!! no instance ids resolved — nothing stopped, check the AWS console"
  elif aws ec2 stop-instances --instance-ids $all_instance_ids >/dev/null; then
    echo "stopped: $all_instance_ids"
  else
    echo "!! stop-instances FAILED — still billing. run: aws ec2 stop-instances --instance-ids $all_instance_ids"
  fi

  remove_nat_gateway_to_stop_billing
  exit 0
}
trap shut_everything_down_and_exit INT TERM

report_failure_and_shut_everything_down() {
  echo "!! $*"
  shut_everything_down_and_exit
}

find_instance_ids_by_name_tag() {
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$1" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text | tr '\t' ' ' | xargs
}

read_terraform_output() {
  terraform -chdir="$TF_DIR" output -raw "$1" 2>/dev/null | xargs
}

wait_for_stopping_instances_to_finish_stopping() {
  local still_stopping_ids
  still_stopping_ids="$(aws ec2 describe-instances --instance-ids "$@" \
    --query 'Reservations[].Instances[?State.Name==`stopping`].InstanceId' --output text | xargs)"
  [[ -n "$still_stopping_ids" ]] && aws ec2 wait instance-stopped --instance-ids $still_stopping_ids
  return 0
}

run_command_on_bastion_over_ssh() {
  ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -i "$SSH_KEY_PATH" "ec2-user@$BASTION_IP" "$@"
}

read_command_line_arguments() {
  if [[ "${1:-}" == "--fresh" ]]; then
    REPLACE_ALL_NODES=1
  fi
}

check_required_tools_and_ssh_key_exist() {
  command -v aws >/dev/null || exit_with_error_message "aws cli not on PATH"
  command -v terraform >/dev/null || exit_with_error_message "terraform not on PATH"
  [[ -f "$SSH_KEY_PATH" ]] || exit_with_error_message "ssh key not found at $SSH_KEY_PATH"
}

build_infrastructure_with_terraform() {
  echo "refreshing infrastructure..."
  NAT_GATEWAY_MAY_EXIST=1

  TERRAFORM_APPLY_ARGUMENTS=(-auto-approve)
  if [[ "$REPLACE_ALL_NODES" == 1 ]]; then
    for node_number in 0 1 2 3 4; do
      TERRAFORM_APPLY_ARGUMENTS+=("-replace=aws_instance.db_node[$node_number]")
    done
  fi

  local terraform_output_file
  terraform_output_file="$(mktemp)"
  terraform -chdir="$TF_DIR" apply "${TERRAFORM_APPLY_ARGUMENTS[@]}" >"$terraform_output_file" 2>&1 \
    || { cat "$terraform_output_file"; rm -f "$terraform_output_file"; exit_with_error_message "terraform apply failed"; }
  rm -f "$terraform_output_file"
}

look_up_node_ids_and_bastion_details() {
  NODE_INSTANCE_IDS="$(read_terraform_output node_instance_ids)"
  [[ -z "$NODE_INSTANCE_IDS" ]] && NODE_INSTANCE_IDS="$(find_instance_ids_by_name_tag 'ameyaDB-node-*')"
  [[ -z "$NODE_INSTANCE_IDS" ]] && exit_with_error_message "could not resolve node instance ids"

  BASTION_INSTANCE_ID="$(read_terraform_output bastion_instance_id)"
  [[ -z "$BASTION_INSTANCE_ID" ]] && BASTION_INSTANCE_ID="$(find_instance_ids_by_name_tag 'ameyaDB-bastion')"
  [[ -z "$BASTION_INSTANCE_ID" ]] && exit_with_error_message "could not resolve bastion instance id"

  BASTION_IP="$(read_terraform_output bastion_ip)"
  [[ -z "$BASTION_IP" ]] && exit_with_error_message "could not resolve bastion_ip"
}

start_website_in_background() {
  echo "starting frontend..."
  ( cd "$ROOT_DIR/frontend" && exec npm run dev >/dev/null 2>&1 ) &
  FRONTEND_PID=$!
  echo "open this link to continue : http://localhost:5173"
}

restart_bastion_machine_and_wait_until_reachable() {
  wait_for_stopping_instances_to_finish_stopping $BASTION_INSTANCE_ID

  local bastion_state
  bastion_state="$(aws ec2 describe-instances --instance-ids $BASTION_INSTANCE_ID \
    --query 'Reservations[].Instances[].State.Name' --output text)"
  if [[ "$bastion_state" == "running" ]]; then
    aws ec2 stop-instances --instance-ids $BASTION_INSTANCE_ID >/dev/null || report_failure_and_shut_everything_down "stop-instances (bastion) failed"
    aws ec2 wait instance-stopped --instance-ids $BASTION_INSTANCE_ID || report_failure_and_shut_everything_down "bastion never stopped"
  fi

  aws ec2 start-instances --instance-ids $BASTION_INSTANCE_ID >/dev/null || report_failure_and_shut_everything_down "start-instances (bastion) failed"

  aws ec2 wait instance-running --instance-ids $BASTION_INSTANCE_ID || report_failure_and_shut_everything_down "bastion never started"

  local attempt_number
  for attempt_number in $(seq 1 40); do
    run_command_on_bastion_over_ssh true 2>/dev/null && break
    [[ "$attempt_number" == 40 ]] && { run_command_on_bastion_over_ssh true; report_failure_and_shut_everything_down "bastion sshd never came up"; }
    sleep 2
  done
}

start_relay_on_bastion_in_background() {
  (
    ssh -tt -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -i "$SSH_KEY_PATH" "ec2-user@$BASTION_IP" "cd $REPO_NAME_ON_BASTION && git pull --quiet && exec python3 -u relay.py"
    rc=$?; echo "!! relay exited (code $rc)"
  ) > >(tee "$RELAY_LOG_FILE") 2>&1 &
  RELAY_PID=$!
}

wait_until_browser_is_connected_to_relay() {
  until grep -q "relay & browser are connected" "$RELAY_LOG_FILE"; do
    kill -0 "$RELAY_PID" 2>/dev/null \
      || report_failure_and_shut_everything_down "relay died before the browser connected — is the bastion's relay.py up to date? (dooby git-pulls on the bastion)"
    sleep 1
  done
}

start_database_nodes_and_wait_until_healthy() {
  wait_for_stopping_instances_to_finish_stopping $NODE_INSTANCE_IDS

  aws ec2 start-instances --instance-ids $NODE_INSTANCE_IDS >/dev/null \
    || report_failure_and_shut_everything_down "start-instances (nodes) failed — see the aws error above (VcpuLimitExceeded = vCPU quota too low)"

  local node_ips
  node_ips="$(terraform -chdir="$TF_DIR" output -json node_ips 2>/dev/null | tr -d '[]"' | tr ',' ' ' | xargs)"
  [[ -z "$node_ips" ]] && node_ips="$(aws ec2 describe-instances --instance-ids $NODE_INSTANCE_IDS \
    --query 'Reservations[].Instances[].PrivateIpAddress' --output text | xargs)"
  echo "node_ips = $node_ips"

  aws ec2 wait instance-status-ok --instance-ids $NODE_INSTANCE_IDS || report_failure_and_shut_everything_down "one or more nodes never became healthy"
}

wait_until_website_and_relay_have_both_stopped() {
  while kill -0 "$FRONTEND_PID" 2>/dev/null || kill -0 "$RELAY_PID" 2>/dev/null; do
    sleep 1
  done
}

run_everything() {
  read_command_line_arguments "$@"
  check_required_tools_and_ssh_key_exist

  build_infrastructure_with_terraform
  look_up_node_ids_and_bastion_details

  start_website_in_background
  restart_bastion_machine_and_wait_until_reachable
  start_relay_on_bastion_in_background
  wait_until_browser_is_connected_to_relay

  start_database_nodes_and_wait_until_healthy

  wait_until_website_and_relay_have_both_stopped
  shut_everything_down_and_exit
}

run_everything "$@"

}
