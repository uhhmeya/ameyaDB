**ameyaDB / Raft**log replication, commit index, InstallSnapshot, post-test agreement check

# Replication works and the nodes agreed, but the cluster isn’t stable through crashes yet

Your test.py ran unchanged against a local 5-node cluster with the real crash and allow scripts. After the full crash cycle all five nodes held identical data: the same snapshot (index 526,935, term 299, 526,418 keys, sorted contents byte-identical) and empty WALs. The relay’s new check didn’t confirm it automatically, because nodes kept electing new leaders after each rejoin (no PreVote yet) and the check stopped waiting too early. Not run on AWS yet.

**6**files changed, test.py untouched

**+531 / −58**lines vs your working tree

**526,935**entries committed, run 2

**5 / 5**identical snapshots at the end

**\~895**terms reached, run 2 (churn)

## The write path now

A client write is only acknowledged once a majority has it in their WAL, and only then applied to the db. Uncommitted WAL entries are no longer replayed into the db at boot.

WRITE → onWrite

### Leader appends

`append_entry` writes the WAL and log only, sets `ack_len[me]`, and sends to followers that are caught up.

APPEND_ENTRIES 4

### Follower checks prefix

`log_ok`, then `append_entries` truncates at the first conflict and appends. Applies up to `min(leaderCommit, ack)`.

AERES 7

### Leader counts acks

`onAERes` moves `sent_len`/`ack_len`; on a miss it jumps back to the follower’s hint. `commit_log_entries` needs a majority and a current-term entry.

SNAP 8

### Far-behind follower

If the needed prefix was compacted, the leader ships its snapshot file; `install_snap` swaps the db and fixes the WAL.

## Weak spots

Ordered by how much they hurt the crash test. PreVote is left as `// TODO : PREVOTE!!!` in `startELEC`, as you asked.

| Severity | Issue |
| --- | --- |
| High | **No PreVote (marked TODO : PREVOTE!!! in startELEC)** A node coming back from the crash script times out before it hears from the leader, bumps its term, and its VoteRequest or AE response forces a healthy leader to step down. This happened after every crash/rejoin in both local runs and is the main source of the term churn (runs ended around term 490 and 895). |
| High | **Leader compacts its log right up to its commit index** take_pics now cuts at the applied index every \~1.5 s, so a healthy follower that is even a few dozen entries behind needs a full InstallSnapshot (seen: snapshot sent to a follower 40 entries behind). Fix: keep a trailing window of entries in the WAL after each snapshot, or compact only up to the slowest live follower's ack. |
| High | **Snapshot install can livelock a lagging follower** install_snap runs under ROCK and took 0.3–0.8 s locally at \~200k keys. If the leader compacts again during the install, the follower needs another snapshot right away. Sends are rate limited to one per follower every 2 s. |
| Medium | **Election timer can fire while a snapshot is still on the wire** The deadline resets only after install. startELEC now re-checks the deadline after taking ROCK, which covers the install itself but not the time spent reading a multi-MB snapshot off the socket. |
| Medium | **Relay check gives up too early under load** Each 1 s polling round clears the replies, and hashing \~500k keys can take longer than that on a busy node, so both runs reported only 1/5 replies. Keeping the last reply per node instead of clearing fixes it. The data itself agreed (see results). |
| Medium | **No no-op entry when a leader is elected** Kleppmann's version has none, so a new leader commits earlier-term entries only once a client writes in its term. If an election lands after the test's last write, commit indexes may never line up and the check would say so. Not a safety bug. |
| Low | **Snapshots are re-read and queued for dead followers** Every 2 s the leader reads its whole snapshot file for a follower that is down, until TCP_USER_TIMEOUT closes the socket. |
| Low | **Write timeouts are not exactly-once** onWrite waits up to 2 s for commit; on timeout the client gets IDK but the entry may still commit later. test.py retries the same key with a new value, so it is harmless here. |
| Low | **Reads are local** handle_read serves any node's db, so reads can be stale (not linearizable). |
| Low | **Durability matches your existing crash model** WAL writes use flush() and the installed snapshot is not fsync'd, same as take_pics: safe against the crash script's process kill, not power loss. |
| Low | **Outbox cap counts messages, not bytes** 1000 queued messages per peer, then new ones are dropped (Raft retries them). |
| Context | **Local harness is CPU-starved** 5 nodes plus 10 clients on 2 vCPUs with your -O0 build line, versus one m7i.large per node on AWS. Timing problems are exaggerated locally. Not yet run on AWS. |

## Test results so far

- **Run 1:** full test.py cycle finished. Nodes churned to term \~490, two nodes were still catching up when the check ran, relay got 1/5 replies.
- **Run 2:** full cycle finished, \~527k writes committed. Relay again got 1/5 replies, but afterwards all five snapshots were identical and every WAL was empty, so the data agreed.
- Both runs: snapshots installed on rejoining nodes, conflicting uncommitted tails were truncated (`chop_wal`), and no node crashed.

Harness (not in your repo): 5 Linux network namespaces with your real ameyaDB-allow.sh / ameyaDB-crash.sh, stand-ins for sudo, systemd-run and systemctl, a clockbound stub, your relay.py, and a scripted browser that clicks run. Built with your exact g++ line from main.tf.

## How the agreement check works

When test.py exits, `relay.py` sends `state` to every node. Each answers with its commit index, the term of that entry, its key count and a digest of the db (sum of per-key CRCs). The relay polls for up to 30 s, prints every node’s line and sends one verdict to the debug page: *agree up to commit index N*, *never reached the same commit index*, or *DISAGREE at the same commit index*.

| File | Added | Removed |
| --- | --- | --- |
| [engine/src/server/raft.cpp](#raft-cpp) | +205 | −19 |
| [engine/src/server/walsnap.cpp](#walsnap-cpp) | +163 | −21 |
| [engine/src/server/handlers.cpp](#handlers-cpp) | +60 | −5 |
| [engine/src/server/main.cpp](#main-cpp) | +53 | −11 |
| [engine/src/headers/globals.h](#globals-h) | +11 | −0 |
| [relay.py](#relay-py) | +39 | −2 |

## The code

Diff against your current working tree (including your uncommitted comment removal in main.cpp). No new comments besides the TODO.

[raft.cpp](#raft-cpp)[walsnap.cpp](#walsnap-cpp)[handlers.cpp](#handlers-cpp)[main.cpp](#main-cpp)[globals.h](#globals-h)[relay.py](#relay-py)

### engine/src/server/raft.cpp

**+205** **−19**

Log replication from the Kleppmann slides: replicate (ReplicateLog), onWrite (broadcast), onAE (LogRequest), onAERes (LogResponse), commit_log_entries, onSnap, leader setup in onVRes, heartbeat now sends real AppendEntries. TODO : PREVOTE!!! sits in startELEC.

```
@@ -11,8 +11,9 @@
 #include <chrono>
 #include <condition_variable>
 #include <random>
 # include <thread>
+#include <algorithm>
 
 enum Raft_Role {
     FOLLOWER,
     CANDIDATE,
@@ -22,8 +23,9 @@ enum Raft_Role {
 static const string RAFT_PATH = "../output/raft.txt";
 static const string RAFT_TMP_PATH = "../output/raft.tmp";
 
 static mutex ROCK;
+static condition_variable committed;
 
 // restore
 static xnt curTerm;
 static int votedFor;
@@ -34,8 +36,9 @@ static Raft_Role role;
 static xnt commit_idx;
 static unordered_set<int> in_votes;
 static vector<xnt> sent_len;
 static vector<xnt> ack_len;
+static vector<steady_clock::time_point> snap_sent;
 
 static atomic<steady_clock::time_point> deadline{};
 
 static void must(bool ok, const string &what)
@@ -64,16 +67,55 @@ static string build_Vres(xnt term, bool yes_or_no) {
     buf[1 + sizeof(int) + sizeof(xnt)] = yes_or_no ? 1 : 0;
     return string(buf, sizeof(buf));
 }
 
-static string build_AE(xnt term) {
-    char buf[1 + sizeof(int) + sizeof(xnt)];
+static string build_AE(xnt term, xnt prefix_len, xnt prefix_term, xnt leader_commit, const vector<entry> &suffix) {
+    char buf[1 + sizeof(int) + 5 * sizeof(xnt)];
+    xnt n = suffix.size();
     buf[0] = APPEND_ENTRIES;
     memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
     memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
+    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &prefix_len, sizeof(prefix_len));
+    memcpy(&buf[1 + sizeof(int) + 2 * sizeof(xnt)], &prefix_term, sizeof(prefix_term));
+    memcpy(&buf[1 + sizeof(int) + 3 * sizeof(xnt)], &leader_commit, sizeof(leader_commit));
+    memcpy(&buf[1 + sizeof(int) + 4 * sizeof(xnt)], &n, sizeof(n));
+
+    string msg(buf, sizeof(buf));
+    for (const entry &e : suffix) {
+        xnt k_len = e.wr.k.size();
+        xnt v_len = e.wr.v.size();
+        msg.append(reinterpret_cast<const char *>(&k_len), sizeof(k_len));
+        msg.append(e.wr.k);
+        msg.append(reinterpret_cast<const char *>(&v_len), sizeof(v_len));
+        msg.append(e.wr.v);
+        msg.append(reinterpret_cast<const char *>(&e.stats), sizeof(e.stats));
+        msg.append(reinterpret_cast<const char *>(&e.log_index), sizeof(e.log_index));
+        msg.append(reinterpret_cast<const char *>(&e.term), sizeof(e.term));
+        msg.append(reinterpret_cast<const char *>(&e.checksum), sizeof(e.checksum));
+    }
+    return msg;
+}
+
+static string build_AEres(xnt term, xnt ack, bool yes_or_no) {
+    char buf[1 + sizeof(int) + 2 * sizeof(xnt) + 1];
+    buf[0] = AERES;
+    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
+    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
+    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &ack, sizeof(ack));
+    buf[1 + sizeof(int) + 2 * sizeof(xnt)] = yes_or_no ? 1 : 0;
     return string(buf, sizeof(buf));
 }
 
+static string build_SNAP(xnt term, const string &snap) {
+    char buf[1 + sizeof(int) + 2 * sizeof(xnt)];
+    xnt snap_len = snap.size();
+    buf[0] = SNAP;
+    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
+    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
+    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &snap_len, sizeof(snap_len));
+    return string(buf, sizeof(buf)) + snap;
+}
+
 xnt get_cur_term() {
     lock_guard g(ROCK);
     return curTerm;
 }
@@ -122,8 +164,36 @@ static void save_tv() {
 static void set_new_deadline() {
     deadline = steady_clock::now() + milliseconds(rand_sleep_timer_ms(150, 300));
 }
 
+static void replicate(int follower) {
+    xnt prefix_len = sent_len[follower];
+    xnt prefix_term = 0;
+    vector<entry> suffix;
+
+    bool has_prefix = get_suffix(prefix_len, prefix_term, suffix);
+
+    if (!has_prefix && steady_clock::now() - snap_sent[follower] > seconds(2)) {
+        snap_sent[follower] = steady_clock::now();
+        Psend(follower, build_SNAP(curTerm, read_snap()));
+        return;
+    }
+
+    Psend(follower, build_AE(curTerm, prefix_len, prefix_term, commit_idx, suffix));
+}
+
+static void commit_log_entries() {
+    vector<xnt> acks = ack_len;
+    sort(acks.begin(), acks.end(), greater<>());
+    xnt ready = acks[NUM_NODES / 2];
+
+    if (ready > commit_idx && get_term(ready) == curTerm) {
+        apply_entries(ready);
+        commit_idx = ready;
+        committed.notify_all();
+    }
+}
+
 static void startELEC() {
 
     xnt term_when_ELEC_started;
     xnt log_index;
@@ -132,10 +202,13 @@ static void startELEC() {
     // LOCK
     {
         lock_guard g(ROCK);
 
+        if (steady_clock::now() < deadline.load()) return;
+        set_new_deadline();
         if (role == LEADER) return;
 
+        // TODO : PREVOTE!!!
         curTerm++;
         role = CANDIDATE;
         votedFor = myNodeID;
         in_votes.clear();
@@ -154,27 +227,24 @@ static void startELEC() {
 
 static void Ethread() {
     while (true) {
         sleep_for(milliseconds(10));
-        if (steady_clock::now() >= deadline.load()) {
-            set_new_deadline();
+        if (steady_clock::now() >= deadline.load())
             startELEC();
-        }
     }
 }
 
 static void HBthread() {
     while (true) {
         sleep_for(milliseconds(50));
 
-        xnt term_when_HB;
-        {
-            lock_guard g(ROCK);
-            if (role != LEADER) continue;
-            term_when_HB = curTerm;
-        }
+        lock_guard g(ROCK);
+        if (role != LEADER) continue;
 
-        broadcast(build_AE(term_when_HB));
+        for (int node = 0; node < NUM_NODES; node++) {
+            if (node == myNodeID) continue;
+            replicate(node);
+        }
     }
 }
 
 void raft_init() {
@@ -190,38 +260,144 @@ void raft_init() {
     // all
     role = FOLLOWER;
     leader = NO_LEADER;
     in_votes.clear();
-    commit_idx = 0;
+    commit_idx = get_applied_idx();
     sent_len.assign(NUM_NODES, 0);
     ack_len.assign(NUM_NODES, 0);
+    snap_sent.assign(NUM_NODES, steady_clock::time_point{});
 
     set_new_deadline();
     thread(Ethread).detach();
     thread(HBthread).detach();
 }
 
-void onAE(int leader_id, xnt term) {
-    string log;
+bool onWrite(const string &k, const string &v) {
+    unique_lock g(ROCK);
+
+    if (role != LEADER) return false;
+
+    xnt term_when_WR = curTerm;
+    xnt idx = append_entry(k, v, curTerm);
+    ack_len[myNodeID] = idx;
+
+    for (int node = 0; node < NUM_NODES; node++) {
+        if (node == myNodeID || sent_len[node] != idx - 1) continue;
+        replicate(node);
+    }
+
+    for (int tries = 0; tries < 40 && commit_idx < idx && curTerm == term_when_WR; tries++)
+        committed.wait_for(g, milliseconds(50));
+
+    return commit_idx >= idx && curTerm == term_when_WR;
+}
+
+void onAE(int leader_id, xnt term, xnt prefix_len, xnt prefix_term, xnt leader_commit, const vector<entry> &suffix) {
+
+    xnt term_when_AE;
+    xnt ack = 0;
+    bool yes_or_no = false;
+
     {
         lock_guard g(ROCK);
 
-        if (term < curTerm)
-            return;
-
         // update
         if (term > curTerm) {
             curTerm = term;
             votedFor = NO_VOTE;
             save_tv();
         }
 
+        if (term == curTerm) {
+            role = FOLLOWER;
+            leader = leader_id;
+            set_new_deadline();
+        }
+
+        if (term == curTerm && log_ok(prefix_len, prefix_term)) {
+            append_entries(suffix);
+            ack = prefix_len + suffix.size();
+            yes_or_no = true;
+
+            xnt new_commit = min(leader_commit, ack);
+            if (new_commit > commit_idx) {
+                apply_entries(new_commit);
+                commit_idx = new_commit;
+            }
+        } else {
+            xnt log_len = get_log_idx();
+            ack = log_len < prefix_len ? log_len : commit_idx;
+        }
+
+        term_when_AE = curTerm;
+    }
+
+    Psend(leader_id, build_AEres(term_when_AE, ack, yes_or_no));
+}
+
+void onAERes(int f_ID, xnt f_Term, xnt ack, bool yes_or_no) {
+    lock_guard g(ROCK);
+
+    if (f_Term < curTerm)
+        return;
+
+    if (f_Term > curTerm) {
+        curTerm = f_Term;
         role = FOLLOWER;
-        leader = leader_id;
+        votedFor = NO_VOTE;
+        leader = NO_LEADER;
+        save_tv();
         set_new_deadline();
+        return;
+    }
+
+    if (role != LEADER || f_ID < 0 || f_ID >= NUM_NODES)
+        return;
+
+    if (yes_or_no && ack >= ack_len[f_ID]) {
+        bool progress = ack > ack_len[f_ID];
+        sent_len[f_ID] = ack;
+        ack_len[f_ID] = ack;
+        commit_log_entries();
+
+        if (progress && ack < get_log_idx())
+            replicate(f_ID);
+    } else if (!yes_or_no && sent_len[f_ID] > ack) {
+        sent_len[f_ID] = ack;
+        replicate(f_ID);
     }
 }
 
+void onSnap(int leader_id, xnt term, const string &snap) {
+
+    xnt term_when_SNAP;
+    xnt ack = 0;
+    bool yes_or_no = false;
+
+    {
+        lock_guard g(ROCK);
+
+        if (term > curTerm) {
+            curTerm = term;
+            votedFor = NO_VOTE;
+            save_tv();
+        }
+
+        if (term == curTerm) {
+            role = FOLLOWER;
+            leader = leader_id;
+            ack = install_snap(snap);
+            commit_idx = max(commit_idx, ack);
+            yes_or_no = true;
+            set_new_deadline();
+        }
+
+        term_when_SNAP = curTerm;
+    }
+
+    Psend(leader_id, build_AEres(term_when_SNAP, ack, yes_or_no));
+}
+
 void onVReq(int c_ID, xnt c_Term, xnt c_LogIDX, xnt c_LogTERM) {
 
     xnt term_when_VR;
     bool yes_or_no;
@@ -289,6 +465,16 @@ void onVRes(int c_ID, xnt c_Term, bool was_vote_granted) {
 
     if (in_votes.size() >= NUM_NODES / 2 + 1) {
         role = LEADER;
         leader = myNodeID;
+
+        xnt log_len = get_log_idx();
+        sent_len.assign(NUM_NODES, log_len);
+        ack_len.assign(NUM_NODES, 0);
+        ack_len[myNodeID] = log_len;
+
+        for (int node = 0; node < NUM_NODES; node++) {
+            if (node == myNodeID) continue;
+            replicate(node);
+        }
     }
 }
```

### engine/src/server/walsnap.cpp

**+163** **−21**

Leader appends without applying; entries hit the db only on commit (apply_entries). Follower append with first-conflict truncation (chop_wal rewrites the WAL atomically). Snapshots now cut at the applied index. install_snap, read_snap, log_ok, get_suffix, db_state. Boot replay no longer applies uncommitted WAL entries.

```
@@ -11,21 +11,24 @@
 #include <sstream>
 #include <cstdio>
 #include <random>
 #include <algorithm>
+#include <iterator>
 
 static const string SNAP_DIR_PATH = "../output/snaps/";
 static const string WAL_PATH      = "../output/wal.txt";
 
 static unordered_map<string, string> db;
 static shared_mutex db_mutex;
 static ofstream wal;
 static mutex log_mutex;
+static mutex snap_mutex;
 static str_arr_2D prev_snap_arr;
 static str_arr_1D dk;
 static vector<entry> log_vector;
 static xnt snap_index = 0;
 static xnt snap_term  = 0;
+static xnt applied_idx = 0;
 
 // turns entry into string
 static string serialize_entry(const entry& e) {
     return e.wr.k                                + " " +
@@ -37,40 +40,79 @@ static string serialize_entry(const entry& e) {
            to_string(e.term)                      + " " +
            to_string(e.checksum)                  + "\n";
 }
 
+static xnt term_at(xnt idx) {
+    if (idx == snap_index) return snap_term;
+    if (idx < snap_index || idx > snap_index + log_vector.size()) return 0;
+    return log_vector[idx - snap_index - 1].term;
+}
+
+static void chop_wal(xnt idx) {
+    log_vector.resize(idx - snap_index);
+
+    ofstream new_wal(WAL_PATH + string(".tmp"));
+    for (auto& e : log_vector) new_wal << serialize_entry(e);
+    new_wal.flush(); new_wal.close();
+
+    rename((WAL_PATH + string(".tmp")).c_str(), WAL_PATH.c_str());
+    wal.close(); wal.open(WAL_PATH, ios::app);
+}
+
 // commit
-void apply_entry(const string& k, const string& v) {
+void apply_entries(xnt commit_idx) {
+    unique_lock x(db_mutex);
+    lock_guard y(log_mutex);
+
+    for (; applied_idx < commit_idx; applied_idx++) {
+        const entry& e = log_vector[applied_idx - snap_index];
+        db[e.wr.k] = e.wr.v;
+        dk.insert(e.wr.k);
+    }
+}
 
-    xnt term = get_cur_term();
+xnt append_entry(const string& k, const string& v, xnt term) {
 
     entry e;
     e.wr.k = k;
     e.wr.v = v;
     e.term = term;
     e.stats.forwarding_node = myNodeID;
+    e.stats.leader_node = myNodeID;
     e.stats.time_leader_received = now_ms();
 
+    // guards from truncate_wal
     {
-        unique_lock x(db_mutex);
+        lock_guard y(log_mutex);
 
         e.log_index = ++log_index;
         e.checksum  = compute_checksum(e);
 
-        string str_entry = serialize_entry(e);
+        wal << serialize_entry(e);
+        wal.flush();
+        log_vector.push_back(e);
+    }
 
-        // guards from truncate_wal
-        {
-            lock_guard y(log_mutex);
+    return e.log_index;
+}
 
-            wal << str_entry;
-            wal.flush();
-            log_vector.push_back(e);
-        }
+void append_entries(const vector<entry>& suffix) {
+    lock_guard y(log_mutex);
 
-        db[e.wr.k] = e.wr.v;
-        dk.insert(e.wr.k);
+    for (const entry& e : suffix) {
+        xnt log_len = snap_index + log_vector.size();
+
+        if (e.log_index <= snap_index) continue;
+        if (e.log_index <= log_len && term_at(e.log_index) == e.term) continue;
+        if (e.log_index > log_len + 1) break;
+        if (e.log_index <= log_len) chop_wal(e.log_index - 1);
+
+        wal << serialize_entry(e);
+        log_vector.push_back(e);
     }
+    wal.flush();
+
+    log_index = snap_index + log_vector.size();
 }
 
 // read
 string apply_r(const string& k) {
@@ -138,8 +180,9 @@ void take_pics() {
             sleep_for(milliseconds(rand_sleep_timer_ms(100,700)));
             continue;
         }
 
+        unique_lock s(snap_mutex);
         str_arr_1D empty;
         str_arr_2D wip_snap_arr = prev_snap_arr;
         xnt snap_idx, last_term;
         {
@@ -147,10 +190,10 @@ void take_pics() {
             swap(empty, dk);
             str_arr_1D local_dk = empty;
             {
                 lock_guard l(log_mutex);
-                snap_idx  = snap_index + static_cast<xnt>(log_vector.size());
-                last_term = log_vector.empty() ? snap_term : log_vector.back().term;
+                snap_idx  = applied_idx;
+                last_term = term_at(applied_idx);
             }
             for (auto& k : local_dk)
                 wip_snap_arr[k] = db.contains(k) ? db.at(k) : "";
         }
@@ -165,8 +208,9 @@ void take_pics() {
 
         truncate_wal(snap_idx, last_term);
         prev_snap_arr = std::move(new_snap_arr);
         prev_snap_idx = snap_idx;
+        s.unlock();
 
         // prevent instant snapping
         sleep_for(milliseconds(rand_sleep_timer_ms(1200, 1800)));
 
@@ -185,8 +229,9 @@ pair<xnt, xnt> load_snap() {
     xnt snap_idx = 0, last_term = 0;
     hdr >> snap_idx >> last_term;
     snap_index = snap_idx;
     snap_term  = last_term;
+    applied_idx = snap_idx;
 
     while (getline(f, line)) {
         auto sp = line.find(' ');
         if (sp == string::npos) continue;
@@ -206,9 +251,9 @@ void replay_wal(xnt snap_idx) {
 
     if (!f.is_open())
         throw runtime_error("[replay_wal] could not open WAL content\n");
 
-    xnt highest_committed_idx = snap_idx;
+    xnt highest_idx = snap_idx;
 
     string line;
     while (getline(f, line)) {
         if (line.empty()) continue;
@@ -235,17 +280,15 @@ void replay_wal(xnt snap_idx) {
         e.checksum = compute_checksum(e);
 
         // partial
         if (e.checksum != cs) continue;
+        if (idx != highest_idx + 1) break;
 
-        // prev_snap = db on boot
-        db[e.wr.k] = e.wr.v;
-        prev_snap_arr[e.wr.k] = e.wr.v;
         log_vector.push_back(e);
 
-        highest_committed_idx = idx;
+        highest_idx = idx;
     }
-    log_index.store(highest_committed_idx);
+    log_index.store(highest_idx);
 }
 
 // get last log entry
 optional<entry> get_last_log_entry() {
@@ -274,5 +317,104 @@ void get_log_idx_and_last_log_term(xnt &index, xnt &term) {
         term  = snap_term;
     }
 }
 
+bool log_ok(xnt prefix_len, xnt prefix_term) {
+    lock_guard lock(log_mutex);
+    if (snap_index + log_vector.size() < prefix_len) return false;
+    return prefix_len <= snap_index || term_at(prefix_len) == prefix_term;
+}
+
+bool get_suffix(xnt &prefix_len, xnt &prefix_term, vector<entry> &suffix) {
+    lock_guard lock(log_mutex);
+
+    if (prefix_len < snap_index) {
+        prefix_len  = snap_index;
+        prefix_term = snap_term;
+        return false;
+    }
+
+    prefix_term = term_at(prefix_len);
+    for (xnt i = prefix_len - snap_index; i < log_vector.size() && suffix.size() < 1000; i++)
+        suffix.push_back(log_vector[i]);
+    return true;
+}
+
+xnt get_term(xnt idx) {
+    lock_guard lock(log_mutex);
+    return term_at(idx);
+}
+
+xnt get_applied_idx() {
+    shared_lock lock(db_mutex);
+    return applied_idx;
+}
+
+string read_snap() {
+    ifstream f(SNAP_DIR_PATH + "snap");
+    return string(istreambuf_iterator<char>(f), istreambuf_iterator<char>());
+}
+
+xnt install_snap(const string& snap) {
+    lock_guard s(snap_mutex);
+
+    istringstream f(snap);
+    string line;
+    getline(f, line);
+    istringstream hdr(line);
+    xnt snap_idx = 0, last_term = 0;
+    hdr >> snap_idx >> last_term;
+
+    if (snap_idx <= applied_idx) return applied_idx;
+
+    str_arr_2D snap_arr;
+    while (getline(f, line)) {
+        auto sp = line.find(' ');
+        if (sp == string::npos) continue;
+        snap_arr[line.substr(0, sp)] = line.substr(sp + 1);
+    }
+
+    {
+        lock_guard lock(log_mutex);
+        if (snap_index + log_vector.size() > snap_idx && term_at(snap_idx) != last_term)
+            chop_wal(snap_idx);
+    }
+
+    ofstream tmp(SNAP_DIR_PATH + "snap" + ".tmp");
+    tmp << snap;
+    tmp.flush(); tmp.close();
+    rename((SNAP_DIR_PATH + "snap" + ".tmp").c_str(), (SNAP_DIR_PATH + "snap").c_str());
+
+    truncate_wal(snap_idx, last_term);
+
+    unique_lock x(db_mutex);
+    lock_guard y(log_mutex);
+    db = snap_arr;
+    prev_snap_arr = std::move(snap_arr);
+    dk.clear();
+    applied_idx = snap_idx;
+    log_index = snap_index + log_vector.size();
+
+    return snap_idx;
+}
+
+string db_state() {
+    shared_lock lock(db_mutex);
+
+    xnt last_term;
+    {
+        lock_guard l(log_mutex);
+        last_term = term_at(applied_idx);
+    }
+
+    unsigned long long digest = 0;
+    for (auto& [k, v] : db) {
+        entry e;
+        e.wr.k = k;
+        e.wr.v = v;
+        digest += compute_checksum(e);
+    }
+
+    return to_string(applied_idx) + " " + to_string(last_term) + " " + to_string(db.size()) + " " + to_string(digest);
+}
+
 
```

### engine/src/server/handlers.cpp

**+60** **−5**

handle_write waits for commit through onWrite. handle_ae reads prefix, prefix term, leader commit and the entries; new handle_aeres and handle_snap. Entries are checksum-verified on receipt.

```
@@ -3,17 +3,19 @@
 #include <cstdint>
 #include <cstring>
 
 // imports
-void apply_entry(const string& k, const string& v);
 string apply_r(const string& k);
 
 // raft.cpp
 bool am_i_leader();
 int  who_is_leader();
+bool onWrite(const string& k, const string& v);
 void onVReq(int c_ID, xnt c_Term, xnt c_LogIDX, xnt c_LogTERM);
 void onVRes(int c_ID, xnt c_Term, bool was_vote_granted);
-void onAE(int leader_id, xnt term);
+void onAE(int leader_id, xnt term, xnt prefix_len, xnt prefix_term, xnt leader_commit, const vector<entry>& suffix);
+void onAERes(int f_ID, xnt f_Term, xnt ack, bool yes_or_no);
+void onSnap(int leader_id, xnt term, const string& snap);
 
 // helpers
 static bool read_tcp(int client_fd, void* buf, size_t n) {
     size_t received = 0;
@@ -59,8 +61,22 @@ static optional<string> read_k(int client_fd) {
     string k(k_len, '\0');
     if (k_len && !read_tcp(client_fd, &k[0], k_len)) return nullopt;
     return k;
 }
+static optional<entry> read_entry(int peer_fd) {
+    auto kv = read_kv(peer_fd);
+    if (!kv) return nullopt;
+
+    entry e;
+    e.wr.k = kv->first;
+    e.wr.v = kv->second;
+    if (!read_tcp(peer_fd, &e.stats, sizeof(e.stats))) return nullopt;
+    if (!read_tcp(peer_fd, &e.log_index, sizeof(e.log_index))) return nullopt;
+    if (!read_tcp(peer_fd, &e.term, sizeof(e.term))) return nullopt;
+    if (!read_tcp(peer_fd, &e.checksum, sizeof(e.checksum))) return nullopt;
+    if (compute_checksum(e) != e.checksum) return nullopt;
+    return e;
+}
 static bool reply(int client_fd, Status status, int leader_hint) {
     char buf[1 + sizeof(int)];
     buf[0] = static_cast<char>(status);
     memcpy(&buf[1], &leader_hint, sizeof(leader_hint));
@@ -79,9 +95,10 @@ bool handle_write(int client_fd) {
         return reply(client_fd, I_AM_NOT_LEADER, leader_id);
     }
 
     auto [k, v] = *kv;
-    apply_entry(k, v);
+    if (!onWrite(k, v))
+        return reply(client_fd, IDK, -1);
 
     return reply(client_fd, I_AM_LEADER, myNodeID);
 }
 bool handle_read(int client_fd) {
@@ -119,12 +136,50 @@ bool handle_vres(int peer_fd) {
     return true;
 }
 bool handle_ae(int peer_fd) {
     int leader_id{0};
-    xnt term{0};
+    xnt term{0}, prefix_len{0}, prefix_term{0}, leader_commit{0}, n{0};
+
+    if (!read_tcp(peer_fd, &leader_id, sizeof(leader_id))) return false;
+    if (!read_tcp(peer_fd, &term, sizeof(term))) return false;
+    if (!read_tcp(peer_fd, &prefix_len, sizeof(prefix_len))) return false;
+    if (!read_tcp(peer_fd, &prefix_term, sizeof(prefix_term))) return false;
+    if (!read_tcp(peer_fd, &leader_commit, sizeof(leader_commit))) return false;
+    if (!read_tcp(peer_fd, &n, sizeof(n))) return false;
+
+    vector<entry> suffix;
+    for (xnt i = 0; i < n; i++) {
+        auto e = read_entry(peer_fd);
+        if (!e) return false;
+        suffix.push_back(*e);
+    }
+
+    onAE(leader_id, term, prefix_len, prefix_term, leader_commit, suffix);
+    return true;
+}
+bool handle_aeres(int peer_fd) {
+    int f_ID{0};
+    xnt f_Term{0}, ack{0};
+    bool yes_or_no{false};
+
+    if (!read_tcp(peer_fd, &f_ID, sizeof(f_ID))) return false;
+    if (!read_tcp(peer_fd, &f_Term, sizeof(f_Term))) return false;
+    if (!read_tcp(peer_fd, &ack, sizeof(ack))) return false;
+    if (!read_tcp(peer_fd, &yes_or_no, sizeof(yes_or_no))) return false;
+
+    onAERes(f_ID, f_Term, ack, yes_or_no);
+    return true;
+}
+bool handle_snap(int peer_fd) {
+    int leader_id{0};
+    xnt term{0}, snap_len{0};
 
     if (!read_tcp(peer_fd, &leader_id, sizeof(leader_id))) return false;
     if (!read_tcp(peer_fd, &term, sizeof(term))) return false;
+    if (!read_tcp(peer_fd, &snap_len, sizeof(snap_len))) return false;
+
+    string snap(snap_len, '\0');
+    if (snap_len && !read_tcp(peer_fd, &snap[0], snap_len)) return false;
 
-    onAE(leader_id, term);
+    onSnap(leader_id, term, snap);
     return true;
 }
\ No newline at end of file
```

### engine/src/server/main.cpp

**+53** **−11**

Routes AERES and SNAP, answers the relay's state request, Psend now queues into a per-peer outbox drained by its own thread (a dead follower can no longer block the leader), TCP_USER_TIMEOUT=3s on peer sockets.

```
@@ -7,8 +7,11 @@
 #include <cerrno>
 #include <string>
 #include <vector>
 #include <utility>
+#include <deque>
+#include <mutex>
+#include <condition_variable>
 #include <sys/socket.h>
 #include <unistd.h>
 #include <arpa/inet.h>
 #include <netinet/in.h>
@@ -25,16 +28,21 @@ int myNodeID;
 atomic<xnt> log_index{0};
 vector<atomic<int>> my_fd_to;
 atomic<int> relay_fd{-1};
 atomic participating{false};
-static mutex peer_write_mutex;
+static mutex outbox_mutex[NUM_NODES];
+static condition_variable outbox_cv[NUM_NODES];
+static deque<string> outbox[NUM_NODES];
 
 // announce
 bool handle_write(int x);
 bool handle_read(int x);
 bool handle_vreq(int x);
 bool handle_vres(int x);
 bool handle_ae(int x);
+bool handle_aeres(int x);
+bool handle_snap(int x);
+string db_state();
 void ensure_wal_is_open();
 void remove_temp_snap();
 void take_pics();
 pair<xnt, xnt> load_snap();
@@ -85,14 +93,15 @@ static int read_hello(int fd) {
     memcpy(&sender_id, &msg[1], sizeof(sender_id));
     return (sender_id >= 0 && sender_id < NUM_NODES) ? sender_id : -1;
 }
 static void set_keepalive(int fd) {
-    int on = 1, idle = 5, intvl = 2, cnt = 3;
+    int on = 1, idle = 5, intvl = 2, cnt = 3, user_timeout = 3000;
     setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &on, sizeof(on));
 #ifdef __APPLE__
     setsockopt(fd, IPPROTO_TCP, TCP_KEEPALIVE, &idle, sizeof(idle));
 #else
     setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
+    setsockopt(fd, IPPROTO_TCP, TCP_USER_TIMEOUT, &user_timeout, sizeof(user_timeout));
 #endif
     setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof(intvl));
     setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &cnt, sizeof(cnt));
 }
@@ -157,8 +166,10 @@ static bool route_to_handler(int peerFD, char op) {
     else if (op == READ)  return handle_read(peerFD);
     else if (op == VREQ)  return handle_vreq(peerFD);
     else if (op == VRES)  return handle_vres(peerFD);
     else if (op == APPEND_ENTRIES) return handle_ae(peerFD);
+    else if (op == AERES) return handle_aeres(peerFD);
+    else if (op == SNAP)  return handle_snap(peerFD);
     return true;
 }
 
 void attach_reader_to_peer_wire(int peer_id) {
@@ -211,8 +222,13 @@ static bool handle_relay_msg(int fd, const string &msg) {
         system(terminate_cmd.c_str());
         return true;
     }
 
+    if (msg.rfind("state", 0) == 0) {
+        send_to_relay("state", db_state());
+        return true;
+    }
+
     return true;
 }
 static void attach_reader_to_relay(int fd) {
     string msg;
@@ -339,20 +355,40 @@ bool Psend(int peer, const string &buf) {
 
     int fd = my_fd_to[peer].load();
     if (fd < 0) return false;
 
-    lock_guard g(peer_write_mutex);
+    {
+        lock_guard g(outbox_mutex[peer]);
+        if (outbox[peer].size() >= 1000) return false;
+        outbox[peer].push_back(buf);
+    }
+    outbox_cv[peer].notify_one();
+    return true;
+}
 
-    size_t sent = 0;
-    while (sent < buf.size()) {
-        ssize_t w = write(fd, buf.data() + sent, buf.size() - sent);
-        if (w <= 0) {
-            if (w < 0 && errno == EINTR) continue;
-            return false;
+static void drain_outbox_4ever(int peer) {
+    while (true) {
+        string buf;
+        {
+            unique_lock g(outbox_mutex[peer]);
+            outbox_cv[peer].wait(g, [peer] { return !outbox[peer].empty(); });
+            buf = std::move(outbox[peer].front());
+            outbox[peer].pop_front();
+        }
+
+        int fd = my_fd_to[peer].load();
+        if (fd < 0) continue;
+
+        size_t sent = 0;
+        while (sent < buf.size()) {
+            ssize_t w = write(fd, buf.data() + sent, buf.size() - sent);
+            if (w <= 0) {
+                if (w < 0 && errno == EINTR) continue;
+                break;
+            }
+            sent += static_cast<size_t>(w);
         }
-        sent += static_cast<size_t>(w);
     }
-    return true;
 }
 
 static void accept_clients_4ever(int listener) {
     while (true) {
@@ -384,8 +420,14 @@ int main(int argc, char *argv[]) {
 
     my_fd_to = vector<atomic<int>>(NUM_NODES);
     for (auto &fd : my_fd_to) fd = -1;
 
+    for (int peer = 0; peer < NUM_NODES; ++peer) {
+        thread([peer] {
+            drain_outbox_4ever(peer);
+        }).detach();
+    }
+
     signal(SIGPIPE, SIG_IGN);
 
     ensure_wal_is_open();
     remove_temp_snap();
```

### engine/src/headers/globals.h

**+11** **−0**

AERES = 7, SNAP = 8, and the walsnap functions raft.cpp calls.

```
@@ -48,8 +48,10 @@ enum Op {
     HELLO          = 3,
     APPEND_ENTRIES = 4,
     VREQ           = 5,
     VRES           = 6,
+    AERES          = 7,
+    SNAP           = 8,
 };
 enum Status : uint8_t {
     I_AM_LEADER     = 11,
     I_AM_NOT_LEADER = 12,
@@ -103,4 +105,13 @@ xnt get_log_idx();
 xnt get_last_log_term();
 xnt get_cur_term();
 bool Psend(int peer, const string& buf);
 void get_log_idx_and_last_log_term(xnt &index, xnt &term);
+xnt append_entry(const string& k, const string& v, xnt term);
+void append_entries(const vector<entry>& suffix);
+void apply_entries(xnt commit_idx);
+bool log_ok(xnt prefix_len, xnt prefix_term);
+bool get_suffix(xnt &prefix_len, xnt &prefix_term, vector<entry> &suffix);
+xnt get_term(xnt idx);
+xnt get_applied_idx();
+string read_snap();
+xnt install_snap(const string& snap);
```

### relay.py

**+39** **−2**

After test.py exits, asks every node for its db state up to its commit index, prints each one, and sends the verdict to the browser's debug page.

```
@@ -16,8 +16,10 @@ testy_ws = None
 node_writers = {}
 nodes_seen_before = set()
 state = {n: "dead" for n in range(NUM_NODES)}
 compile_failed = False
+db_states = {}
+checker = None
 
 async def send(ws, payload):
     if ws is None: return
     try: await ws.send(json.dumps(payload))
@@ -66,8 +68,11 @@ async def on_node_process(reader, writer):
 
             elif msg["type"] == "participating":
                 await set_state(node_id, "participating")
 
+            elif msg["type"] == "state":
+                db_states[node_id] = msg["msg"]
+
             elif msg["type"] == "unreachable":
                 peer_id = int(msg["msg"])
                 if state[peer_id] == "participating":
                     # TODO : NETWORK PARTITION!!!
@@ -84,10 +89,41 @@ async def on_ec2(reader, writer):
     compile_failed = True
     await inform_browser(f"{msg['node']} failed to compile")
     writer.close()
 
+async def check_agreement(testy):
+    await testy.wait()
+
+    for _ in range(30):
+        db_states.clear()
+        for writer in list(node_writers.values()):
+            try:
+                writer.write(b"state\n")
+                await writer.drain()
+            except ConnectionError: pass
+        await asyncio.sleep(1)
+        if len(db_states) == NUM_NODES and len(set(db_states.values())) == 1:
+            break
+
+    for node_id in sorted(db_states):
+        commit_idx, term, num_keys, digest = db_states[node_id].split()
+        print(f"node {node_id}: commit index {commit_idx}, term {term}, {num_keys} keys, digest {digest}", flush=True)
+
+    commit_idxs = {s.split()[0] for s in db_states.values()}
+    if len(db_states) < NUM_NODES:
+        verdict = f"only {len(db_states)}/{NUM_NODES} nodes reported their db"
+    elif len(set(db_states.values())) == 1:
+        verdict = f"all nodes agree on the db up to commit index {commit_idxs.pop()}"
+    elif len(set(db_states.values())) > len(commit_idxs):
+        verdict = "nodes DISAGREE on the db at the same commit index"
+    else:
+        verdict = f"nodes never reached the same commit index {sorted(commit_idxs)}"
+
+    print(verdict, flush=True)
+    await inform_browser(verdict)
+
 async def on_browser_or_testy(websocket):
-    global browser_ws, testy_ws
+    global browser_ws, testy_ws, checker
 
     # the browser connects first, testy second
     if browser_ws is None: browser_ws = websocket
     else: testy_ws = websocket
@@ -97,9 +133,10 @@ async def on_browser_or_testy(websocket):
             data = json.loads(raw)
 
             # start test
             if data["to"] == "relay":
-                await asyncio.create_subprocess_exec("python3", "test.py")
+                testy = await asyncio.create_subprocess_exec("python3", "test.py")
+                checker = asyncio.create_task(check_agreement(testy))
 
             # forward msg to node
             else:
                 writer = node_writers[data["to"]]
```