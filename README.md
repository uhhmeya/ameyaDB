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

# Problem Solving
I wrongly thought that if node B report's that its connection with A breaks while there is no network issue, then that
must mean that A died. This is false because there is a delay between when a tcp connection breaks, and when the node notices.
This caused a bug where a quick reconnect caused a node to falsely report a death. I fixed this by updating the firewall
so that it blocks the FIN packets sent to its peers but not the relay. This lets the relay know which nodes are dead or alive
without the clumsy report system!

# Chaos testing
test.py breaks the cluster on purpose and judges what happens. The run page picks what to break.
1. random chaos : crashes, cut links, slow links, lost msgs, one way links, slow disks & frozen processes at random moments, on top of each other. The seed comes from the OS so no two runs are alike, and it is saved with each run (in the downloaded run file and the compare page's csv).
2. handmade edge case : one of 24 situations that random chaos almost never lands on (`SCENARIOS` in chaos.py)
3. sweep : the same test many times with one knob turned further each run (`SWEEPS` in chaos.py)

After every run testy checks that there was one leader per term, one vote per term, no term went back, every node applied the same entries in the same order, every acked write survived & all 5 nodes agree.
If a check fails, the database is cleared on all 5 nodes before the next run. The relay owns the data epoch now, so there is no constant to bump.

| file | what it is |
| --- | --- |
| test.py | runs one test: clients, phases, numbers, verdict |
| chaos.py | every fault, every handmade edge case, every sweep |
| checks.py | what testy knows about the cluster & how it judges a run |
| selftest.py | tests for chaos.py + checks.py, no cluster needed: `python3 selftest.py` |
| relay.py | passes msgs between browser, testy & nodes, owns the data epoch |

# Research switches
The run page has two tick boxes, prevote & checkquorum, and a box for more flags. Every node gets them as flags.
They change nothing yet. The code that reads them is the part left to write:
1. `// TODO : PREVOTE!!!` in `startELEC()` in raft.cpp, behind `prevote_on()`
2. `// TODO : CHECKQUORUM!!!` in `HBthread()` in raft.cpp, behind `checkquorum_on()`
3. `get_flag("name", fallback)` reads any other flag, `election_ms()` & `heartbeat_ms()` are the timers

The question, the hypotheses & the experiments are in the research brief: https://claude.ai/artifact/ToDGC2ezmaYV5ZqjsWeMwq

# Getting new code onto the cluster
1. git commit + git push. The bastion git pulls & every node clones on boot, so nothing new runs until it is pushed
2. `./dooby.sh --fresh` once after pulling this change (the -O2 build flag lives in each node's boot script)
3. `./dooby.sh` after that

# Looking at a saved run without the cluster
1. `cd frontend && npm run dev`
2. open http://localhost:5173 & pick the file you downloaded from the live page

# Figures for a paper
Print the live or compare page (cmd + P, save as PDF). Every chart comes out as a vector figure on a white background.

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











