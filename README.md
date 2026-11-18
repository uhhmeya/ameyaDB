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
6. Found that terminating a process is not enough to simulate crash since the kernel cleanly closes sockets & FINs every peer. Fixed by jumping an IPTABLES chain off both INPUT & OUTPUT hooks to drop mesh traffic before the kill, destroying FIN/RST packets & Requiring the nodes to infer death from timeout – correctly simulating real crash behavior

# Problem Solving!
If node **B** dies while connected to node **A**, then **A** reports to the observer that **A<->B** is broken.
A connection breaks either when a node dies or when the network fails.
I assumed that if the network is healthy, and **A** reports that **A<->B** is broken, then **B** must necessarily be dead.
This is wrong because there is a delay between when A<->B breaks, and when A notices that A<->B is broken
When A<->B is broken because B dies, B can reconnect to **A** before **A** can notice that the original connection was broken
The error above caused a bug where the observer received a false report
I fixed this by removing the firewalls in the crash script between the nodes and the observer.
I fixed this by giving the observer its own death signal. I removed the firewall in the crash script between the node 
and the observer so that it now receives a crashing node's FIN packet. This confirms a node's death to the observer while
still leaving it ambiguous to the cluster, correctly simulating real crash behavior. 

# usage
1. download project & cd to it
2. ameyaDB % chmod +x dooby.sh && ./dooby.sh
3. that's it :)

# Why is my IDE not recognizing the CPP files?
1. run `cmake -S . -B build` from `engine\`
2. click the `file` on the top left of your screen
3. click invalidate caches
4. click invalidate & restart

# How to run script
chmod +x dooby.sh && ./dooby.sh

# ./dooby.sh --fresh
run this everytime terraform/dooby/packer is updated

# In Raft, you have to infer death but this is how you can know for sure!
To simulate real crash behavior, the ec2s create a firewall before they terminate the process running on it. 
The firewall blocks a FIN packet from being sent to the cluster by blocking ports 8080-8084. This means it
will still send a FIN packet to the relay before the process dies. Therefore, if a node is not connected to the 
relay, it is certainly dead. 




