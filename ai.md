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
