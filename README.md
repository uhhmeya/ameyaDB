# ameyaDB
Stores Key-Val pairs over 5 EC2s each in a different AZ. Nodes use RAFT Consensus, incremental snapshotting, & WAL log.
Nodes forward messages to browser over a relay server on the bastion to display behavior & performance of cluster
during various raft edge cases

# High Level Overview
1. Built & Tested WAL + incremental snapshot crash recovery mechanism to restore DB state after arbitrary crashes.
2. Programmed coordinator-less TCP connection where nodes find peers in any boot order after arbitrary crashes.
3. Invented amGPT, a tool for sending messages from nodes to a React frontend over a relay server to debug crash behavior across cluster.
5. Provisioned 5 node AWS cluster with Terraform with persistent EBS volumes, VPC networking, & per node DNS via Route 53.
6. Added tool that lets browser terminate node, control who the node connects to, & control when node comes back up.

# Technical Details
1. Found race where kernel could reuse a file-descriptor(FD) that my process still thought was in use, fixed by changing which method closes the FD
2. Found race where follower could ACK a dead leader which hits a closed socket which crashes the follower. Fixed by ignoring SIGPIPE.
3. Handled the mid-flush crash data loss edge case by pouring writes into a temp file then atomically renaming it
4. Found race where crash recovery could re-order writes. Fixed it by flushing to WAL and assigning log index under one lock.
5. Found that if you grab dirty keys when building the snap and a crash occurs, then there's a race window where a write can be applied without the key being marked dirty. (data loss)

# usage
1. download project & cd to it
2. ameyaDB % chmod +x dooby.sh && ./dooby.sh
3. that's it :)

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

# How to run script
chmod +x dooby.sh && ./dooby.sh

# Run this when you're done working
aws ec2 stop-instances --instance-ids i-0e6e669af96efd2b2





