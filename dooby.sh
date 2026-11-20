#!/usr/bin/env bash

# =============================================================================
#  dooby.sh  --  start the ameyaDB cluster in AWS, then shut it all down again
# =============================================================================
#
#   ./dooby.sh           start stopped instances (fast, keeps disks + IPs)
#   ./dooby.sh --fresh   terraform-replace all 5 nodes (slow, clean slate)
#
# THE STORY OF A RUN, IN PLAIN ENGLISH
#   1. Make sure aws, terraform and the ssh key are available.
#   2. Run terraform so the infrastructure exists (this also brings back the
#      NAT gateway, which costs money while it exists).
#   3. Look up the AWS ids of the 5 database nodes and the bastion machine.
#   4. Start the website (frontend) on this computer: http://localhost:5173
#   5. Restart the bastion machine and start relay.py on it.
#   6. Wait until you open the website and it connects to the relay.
#   7. Only then start the 5 database nodes and wait until they are healthy.
#   8. Keep running until you press Ctrl-C (or the website / relay stops).
#   9. Clean up: stop the website + relay, stop ALL instances so nothing keeps
#      billing, and delete the NAT gateway again.
#
# Whenever something goes wrong the script still goes to step 9, so you are
# never left paying for machines you forgot about.

# Must run under bash: zsh doesn't word-split $ids, so every aws call would get
# all instance ids glued into ONE argument ("InvalidInstanceID.Malformed").
# If launched via zsh/sh (e.g. an IDE interpreter setting), re-exec in bash.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi

set -uo pipefail

# Everything below lives inside one big { ... } block. Bash reads a whole block
# before running any of it, so editing this file while it runs can't break it.
{

# -----------------------------------------------------------------------------
# SETTINGS: fixed values used throughout the script
# -----------------------------------------------------------------------------

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # the folder this script lives in
TF_DIR="$ROOT_DIR/terraform"                               # where the terraform files are
SSH_KEY_PATH="$HOME/.ssh/ameyaDB"                          # ssh key used to log in to the bastion
REPO_NAME_ON_BASTION="ameyaDB"                             # git repo folder on the bastion machine
export AWS_REGION="${AWS_REGION:-us-east-1}"

# Terraform flags that destroy ONLY the NAT gateway, its elastic IP and its
# route table (nat_enabled=false), and nothing else.
TERRAFORM_FLAGS_THAT_REMOVE_NAT="-var nat_enabled=false -target=aws_route_table.private -target=aws_nat_gateway.geochron -target=aws_eip.nat"

# -----------------------------------------------------------------------------
# STATE: things the script remembers while it runs
# -----------------------------------------------------------------------------

REPLACE_ALL_NODES=0                  # 1 when you ran ./dooby.sh --fresh
NODE_INSTANCE_IDS=""                 # AWS ids of the 5 database nodes
BASTION_INSTANCE_ID=""               # AWS id of the bastion machine
BASTION_IP=""                        # public IP address of the bastion machine
FRONTEND_PID=""                      # process id of the website running on this computer
RELAY_PID=""                         # process id of the ssh session running relay.py
ALREADY_SHUT_DOWN=0                  # 1 once shutdown has started (so it never runs twice)
NAT_GATEWAY_MAY_EXIST=0              # 1 once terraform may have created the NAT gateway
RELAY_LOG_FILE="$(mktemp)"           # copy of everything relay.py prints

# =============================================================================
# SHUTTING DOWN: stop billing and clean up
# =============================================================================

# Print an error, remove the NAT gateway, and quit with a failure code.
# ALREADY_SHUT_DOWN=1 goes first: a Ctrl-C during the teardown must not hijack
# this exit into shut_everything_down_and_exit, which would swallow the
# "still billing" warning and exit 0.

exit_with_error_message() {
  printf '!! %s\n' "$*" >&2
  ALREADY_SHUT_DOWN=1
  remove_nat_gateway_to_stop_billing
  exit 1
}

# Delete the NAT gateway + its elastic IP, because they bill by the hour.
# Does nothing if terraform never got as far as creating them.
remove_nat_gateway_to_stop_billing() {
  [[ "$NAT_GATEWAY_MAY_EXIST" == 1 ]] || return 0
  NAT_GATEWAY_MAY_EXIST=0
  echo "removing NAT gateway + EIP (~1 min, let it finish)..."
  local terraform_output_file; terraform_output_file="$(mktemp)"
  # shellcheck disable=SC2086  # TERRAFORM_FLAGS_THAT_REMOVE_NAT is a flag list on purpose
  if terraform -chdir="$TF_DIR" apply -auto-approve -input=false $TERRAFORM_FLAGS_THAT_REMOVE_NAT >"$terraform_output_file" 2>&1; then
    echo "NAT gateway removed"
  else
    cat "$terraform_output_file"
    echo "!! NAT teardown FAILED — still billing. run: terraform -chdir=$TF_DIR apply $TERRAFORM_FLAGS_THAT_REMOVE_NAT"
  fi
  rm -f "$terraform_output_file"
}

# Stop one process and every process it started (its children, grandchildren...).
stop_process_and_all_its_children() {
  local process_id="${1:-}" child_process_id
  [[ -z "$process_id" ]] && return 0
  for child_process_id in $(pgrep -P "$process_id" 2>/dev/null || true); do
    stop_process_and_all_its_children "$child_process_id"
  done
  kill "$process_id" 2>/dev/null || true
}

# The full shutdown: stop the website and relay, stop every AWS instance,
# delete the NAT gateway, then exit. Runs on Ctrl-C and at the end of a normal run.
shut_everything_down_and_exit() {
  [[ "$ALREADY_SHUT_DOWN" == 1 ]] && return; ALREADY_SHUT_DOWN=1
  echo ""

  stop_process_and_all_its_children "$FRONTEND_PID"
  stop_process_and_all_its_children "$RELAY_PID"
  rm -f "$RELAY_LOG_FILE"

  local all_instance_ids="$(echo "$NODE_INSTANCE_IDS $BASTION_INSTANCE_ID" | xargs)"   # always stop bastion too -- no idle billing between runs
  if [[ -z "$all_instance_ids" ]]; then
    echo "!! no instance ids resolved — nothing stopped, check the AWS console"
  elif aws ec2 stop-instances --instance-ids $all_instance_ids >/dev/null; then
    echo "stopped: $all_instance_ids"
  else
    echo "!! stop-instances FAILED — still billing. run: aws ec2 stop-instances --instance-ids $all_instance_ids"
  fi

  remove_nat_gateway_to_stop_billing   # last: only after the nodes have been told to stop
  exit 0
}
trap shut_everything_down_and_exit INT TERM   # pressing Ctrl-C triggers the full shutdown

# Print a message, then do the full shutdown.
report_failure_and_shut_everything_down() {
  echo "!! $*"
  shut_everything_down_and_exit
}

# =============================================================================
# SMALL HELPERS: little building blocks used by the steps further down
# =============================================================================

# Find AWS instance ids by their Name tag (wildcards allowed, e.g. 'ameyaDB-node-*').
# Used as a fallback when terraform has no answer.
find_instance_ids_by_name_tag() {
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$1" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text | tr '\t' ' ' | xargs
}

# Ask terraform for one of its saved output values (e.g. bastion_ip).
read_terraform_output() {
  terraform -chdir="$TF_DIR" output -raw "$1" 2>/dev/null | xargs
}

# Wait for any of the given instances that are still 'stopping' (from a previous
# run) to finish stopping, because start-instances rejects instances in that state.
wait_for_stopping_instances_to_finish_stopping() {
  local still_stopping_ids
  still_stopping_ids="$(aws ec2 describe-instances --instance-ids "$@" \
    --query 'Reservations[].Instances[?State.Name==`stopping`].InstanceId' --output text | xargs)"
  [[ -n "$still_stopping_ids" ]] && aws ec2 wait instance-stopped --instance-ids $still_stopping_ids
  return 0
}

# Run a command on the bastion machine over ssh (extra arguments = the command).
run_command_on_bastion_over_ssh() {
  ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -i "$SSH_KEY_PATH" "ec2-user@$BASTION_IP" "$@"
}

# =============================================================================
# THE STEPS: one function per step of a run (they are called in order at the bottom)
# =============================================================================

# Step 0: note whether you typed --fresh.
read_command_line_arguments() {
  if [[ "${1:-}" == "--fresh" ]]; then
    REPLACE_ALL_NODES=1
  fi
}

# Step 1: make sure the tools and the ssh key we need are really there.
check_required_tools_and_ssh_key_exist() {
  command -v aws >/dev/null || exit_with_error_message "aws cli not on PATH"
  command -v terraform >/dev/null || exit_with_error_message "terraform not on PATH"
  [[ -f "$SSH_KEY_PATH" ]] || exit_with_error_message "ssh key not found at $SSH_KEY_PATH"
}

# Step 2: run terraform so the infrastructure exists. With --fresh, also
# destroy and rebuild all 5 database nodes (db_node[0] .. db_node[4]).
build_infrastructure_with_terraform() {
  echo "refreshing infrastructure..."
  NAT_GATEWAY_MAY_EXIST=1   # from here on, any exit path must delete the NAT again

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

# Step 3: work out the AWS ids of the nodes and the bastion, and the bastion's IP.
# Ask terraform first; if it has nothing, search AWS by Name tag instead.
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

# Step 4: start the website on this computer, in the background.
start_website_in_background() {
  echo "starting frontend..."
  ( cd "$ROOT_DIR/frontend" && exec npm run dev >/dev/null 2>&1 ) &
  FRONTEND_PID=$!
  echo "open this link to continue : http://localhost:5173"
}

# Step 5a: switch the bastion machine off and on again, and wait until you can ssh into it.
#
# order matters: relay.py keeps ports 9000/9001 closed until the browser attaches,
# and nodes only start after that — a node can never reach a browserless relay.
restart_bastion_machine_and_wait_until_reachable() {
  wait_for_stopping_instances_to_finish_stopping $BASTION_INSTANCE_ID

  # always stop -> start (never just "start if stopped"). A stop kills every
  # process on the box, so this guarantees no leftover relay.py -- no pkill
  # needed -- and it's the same EIP either way, so BASTION_IP never changes.
  local bastion_state
  bastion_state="$(aws ec2 describe-instances --instance-ids $BASTION_INSTANCE_ID \
    --query 'Reservations[].Instances[].State.Name' --output text)"
  if [[ "$bastion_state" == "running" ]]; then
    aws ec2 stop-instances --instance-ids $BASTION_INSTANCE_ID >/dev/null || report_failure_and_shut_everything_down "stop-instances (bastion) failed"
    aws ec2 wait instance-stopped --instance-ids $BASTION_INSTANCE_ID || report_failure_and_shut_everything_down "bastion never stopped"
  fi

  aws ec2 start-instances --instance-ids $BASTION_INSTANCE_ID >/dev/null || report_failure_and_shut_everything_down "start-instances (bastion) failed"

  # instance-running + the ssh retry loop below is enough for the bastion --
  # waiting for full status checks would add minutes for nothing
  aws ec2 wait instance-running --instance-ids $BASTION_INSTANCE_ID || report_failure_and_shut_everything_down "bastion never started"

  # try to ssh in every 2 seconds, up to 40 times
  local attempt_number
  for attempt_number in $(seq 1 40); do
    run_command_on_bastion_over_ssh true 2>/dev/null && break
    [[ "$attempt_number" == 40 ]] && { run_command_on_bastion_over_ssh true; report_failure_and_shut_everything_down "bastion sshd never came up"; }
    sleep 2
  done
}

# Step 5b: ssh into the bastion, pull the latest code, and run relay.py there
# in the background. Everything relay.py prints is also saved to RELAY_LOG_FILE.
start_relay_on_bastion_in_background() {
  (
    ssh -tt -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -i "$SSH_KEY_PATH" "ec2-user@$BASTION_IP" "cd $REPO_NAME_ON_BASTION && git pull --quiet && exec python3 -u relay.py"
    rc=$?; echo "!! relay exited (code $rc)"
  ) > >(tee "$RELAY_LOG_FILE") 2>&1 &
  RELAY_PID=$!
}

# Step 6: pause until you have opened the website and it has connected to the relay.
wait_until_browser_is_connected_to_relay() {
  until grep -q "relay & browser are connected" "$RELAY_LOG_FILE"; do
    kill -0 "$RELAY_PID" 2>/dev/null \
      || report_failure_and_shut_everything_down "relay died before the browser connected — is the bastion's relay.py up to date? (dooby git-pulls on the bastion)"
    sleep 1
  done
}

# Step 7: start the 5 database nodes, show their IPs, and wait until they are healthy.
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

# Step 8: keep running until BOTH the website and the relay have stopped
# (normally you press Ctrl-C long before that).
wait_until_website_and_relay_have_both_stopped() {
  while kill -0 "$FRONTEND_PID" 2>/dev/null || kill -0 "$RELAY_PID" 2>/dev/null; do
    sleep 1
  done
}

# =============================================================================
# MAIN: the whole run, from start to finish
# =============================================================================

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
