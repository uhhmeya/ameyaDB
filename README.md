# ameyaDB
Stores Key-->Value pairs across 5 nodes. Each node is an EC2 in a different AZ. 
Cluster agrees on order of writes applied via the RAFT consensus algorithm. 
Incremental snapshotting + WAL log is used so that each node survives crash.
Nodes forward messages to browser over a relay server that runs on your device.
Browser displays behavior of cluster during various RAFT edge cases

# usage
run `npm run dev` from `/ameyaDB/frontend`
run `python3 test.py` from `/ameyaDB`

# main.cpp
"Putting X on wire" means X is a thread that is reading bytes from wire
Socket is end of wire that reads and writes bytes. Socket is identified by FD.
You can read from & write to an FD at the same time!
However, you can't have 2 threads writing 2 an FD at the same time.

- **`initiate(peer_id)`**
  - establish TCP connection & send hello msg
- **`attach_listener_to_port(myPort)`**
- **`read_hello(FD)`**
  - called by acceptor. Reads hello msg & returns initiators nodeID
- **`keep_initiator_on_wire(peer_id)`**
  - initiates tcp connection to assigned peer if wire breaks
  - keeps reader on initiator's socket
- **`put_acceptor_on_wire(FD)`**
  - called when listener receives SYN packet
  - keeps reader on acceptor's socket
- **`dispatch(FD)`**
  - sends messages to the proper handler
- **`accept_forever(listener)`**
  - parking lot for  all nodes' main threads
  - creates acceptor threads and calls `put_acceptor_on_wire()` when it receives SYN packet
- **`main`**
  - restores DB from wal & connects cluster

# handlers.cpp
Parses KV to wire & sends it to walsnap

# walsnap.cpp
- **`apply_entry`**
  - write
- **`apply_r`**
  - read
- **`ensure_wal_is_open`**
- **`remove_temp_snap`**
  - remove temp snap on reboot
- **`truncate_wal`**
  - truncate wal
- **`take_pics`**
  - create snapshots
- **`load_snap`**
  - load snap into DB
- **`replay_wal`**
  - replay wal entry not covered by snap
- **`get_last_log_entry`**

# Why is my IDE not recognizing the CPP files?
1. run `cmake -S . -B build` from `engine\`
2. click the `file` on the top left of your screen
3. click invalidate caches
4. click invalidate & restart

# How to SSH into an ec2
1. **ameyaDB %** ssh ec2-user@100.48.196.227
2. **bastion %** ssh ec2-user@node-0.ameyadb.internal

# How to update AMI
1. **ameyaDB %** which packer
2. console output has to be `/opt/homebrew/bin/packer` 
3. update the packer file
4. **packer %** packer init ameyaDBnode.pkr.hcl
5. **packer %** packer validate ameyaDBnode.pkr.hcl
6. **packer %** packer build ameyaDBnode.pkr.hcl
7. console output has to be us-east-1 : `ami-xxx`
8. **terraform %** terraform plan -var="db_node_ami=`ami-xxx`
9. console output must show 5 instances + 5 volume attachments replaced + 0 ebs volumes
10. **terraform %** terraform apply -var="db_node_ami=`ami-xxx`

# Details
1. Built crash recovery using WAL replay and incremental snapshots, tested to ensure durability across arbitrary crashes
2. Buffered writes into temp files for WAL truncation and snapshot publishing to prevent unrecoverable EBS state on mid-flush crash
3. Identified race condition allowing stale entries to overwrite newer ones on crash recovery ; Fixed it by flushing to WAL and assigning log index under one lock.
4. Identified atomic grabbing of dirty keys during snapshot construction allows for data loss if a crash occurs between snapshot cycles ; Fixed by marking keys dirty under DB lock
5. Implemented a cluster connection protocol over TCP wire where nodes discover peers in any boot order. No coordinator. Survives arbitrary crashes.
6. Identified race condition where a follower's ACK to the leader can hit a broken wire if the leader died, crashing the follower via SIGPIPE.
7. Replaced SIGPIPE with SIG\_IGN so the failed write returns safely instead of crashing the process.  This lets the connection tear down, and parks the follower with \textbf{surgical precision}.
8. Built ThreadTracer, a tool that streams thread lifecycle events from each node through a relay server into a live React UI, surfacing TCP handshake and crash order to help debug silent network failures.
9. Identified race condition where kernel can hand out a file descriptor(FD) that my process wrongly thinks is in use. Fixed by changing which method closes the FD
10. Connected a Packer-built golden AMI to Terraform, replacing manual per-node dependency setup with one reproducible image shared across all 5 nodes.


   