# ameyaDB

A distributed key-value store built in C++ with crash recovery, snapshotting, and WAL-based durability. Designed to run across a 3-node cluster on AWS EC2, with a local single-node test mode.

---

## Architecture

```
clients.cpp          →   TCP   →   main.cpp (server)
                                      ├── handlers.cpp   (read/write dispatch)
                                      ├── db.cpp         (WAL, snapshots, replay)
                                      └── raft.cpp       (leader election)
```

**Key-Value Format**
- Keys: `k0` – `k9`
- Values: `v0` – `v999`

**TCP Wire Format**
```
write:  op(1) | klen(4) | k | vlen(4) | v
read:   op(1) | klen(4) | k
```

---

## Durability Model

Every write goes through three steps in order:

1. **WAL append** — serialized write record flushed to `wal.txt`
2. **DB update** — in-memory `unordered_map` updated under write lock
3. **Dirty key tracked** — key added to `dk` set for next snapshot

On reboot, the server recovers state by:
1. Loading the latest snapshot from `output/snaps/`
2. Replaying all WAL entries with `log_index >= idx_during_snap`
3. Resuming `log_index` from the last replayed entry

**Snapshotting** runs on a background thread every ~1 second, but only if at least 100 new writes have occurred since the last snapshot. After a snapshot is written atomically (`.tmp` → `.txt` rename), the WAL is truncated to discard entries already covered by the snapshot.

---

## Crash Recovery Guarantee

ameyaDB guarantees that after a crash and reboot, every **acknowledged** write is present in the database. Writes that were in-flight at crash time (sent but not yet acked) may or may not be present — this is expected behavior.

---

## Project Structure

```
engine/
├── src/
│   ├── server/
│   │   ├── main.cpp         # Server entrypoint, TCP listener, thread dispatch
│   │   ├── handlers.cpp     # handle_write / handle_read
│   │   ├── db.cpp           # WAL, snapshots, load_snap, replay_wal
│   │   └── raft.cpp         # Election timer, start_election
│   ├── headers/
│   │   ├── globals.h        # Shared globals, enums, path constants
│   │   ├── handlers.h
│   │   ├── db.h
│   │   ├── raft.h
│   │   └── wr.h             # Write record struct
│   ├── clients.cpp          # Local test client (30 concurrent writers)
│   └── output/
│       ├── binary/          # Compiled executables
│       ├── snaps/           # Snapshot files (snap.<idx>.txt)
│       ├── wal.txt          # Write-ahead log
│       ├── acks.txt         # Acknowledged writes (test use)
│       └── crash            # Sentinel file (signals test.py to crash server)
├── terraform/               # EC2 + bastion provisioning
└── test.py                  # Local crash recovery test
```

---

## Local Test

The local test spins up a single server node, runs 30 concurrent client threads doing 30,000 total writes, crashes the server mid-flight, reboots it, and asserts that every acknowledged write survived.

**Run:**
```bash
python3 test.py
```

**What it does:**
1. Kills any zombie processes on port 8080
2. Clears old WAL, snapshots, acks, and sentinel files
3. Compiles server and client with `-Dlocal_test`
4. Starts the server (`node_id = 0`)
5. Starts 30 client threads writing concurrently
6. Waits for 15,000 acknowledged writes, then crashes the server
7. Reboots the server and asserts:
    - No orphaned `.tmp` snapshot files
    - At most one snapshot present
    - WAL contains no entries older than the snapshot
    - Every key in `acks.txt` reads back the correct value

**Pass output:**
```
=== CRASH TEST PASSED ===
```

---

## Deploy (AWS EC2)

Infrastructure is provisioned with Terraform. Each node is an EC2 instance behind a bastion host.

```bash
./deploy <node_id>
```

The deploy script:
1. Runs `terraform apply` to provision infrastructure
2. SSHes through the bastion into `node-<id>.ameyadb.internal`
3. Clones or pulls the latest code from GitHub
4. Compiles the server with the AWS SDK linked
5. Starts the node

**Node addresses (internal):**
```
node-0.ameyadb.internal
node-1.ameyadb.internal
node-2.ameyadb.internal
```

---

## Build Flags

| Flag | Effect |
|---|---|
| `-Dlocal_test` | Uses local file paths, skips AWS SDK, enables sentinel/ack files |
| *(no flag)* | Uses `/var/log/ameyaDB/` paths, enables SNS/SQS replication |

---

## Dependencies

**Local:**
- `g++` with C++20 support
- Python 3

**EC2:**
- AWS SDK for C++ (`sns`, `sqs`, `core`, `crt`)
- Terraform