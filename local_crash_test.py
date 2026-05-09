#!/usr/bin/env python3

import os
import signal
import socket
import struct
import subprocess
import time

SERVER_DIR   = "engine/src/server"
CLIENT_DIR   = "engine/src"
SNAP_DIR     = "engine/src/server/snapshots"
WAL_PATH     = "engine/src/server/wal.log"
GLOBAL_WAL   = "engine/src/server/global_wal.txt"
SENTINEL     = "engine/src/server/ready_to_crash"

SERVER_PORT          = 8080
MIN_ACKS_BEFORE_CRASH = 15000   # passed to local_test as CLI arg

READ_OP = 2

# ── build ─────────────────────────────────────────────────────────────────────
def build():
    print("[build] compiling server...")
    subprocess.run(
        ["g++", "-std=c++20", "-Dlocal_test", "-o", "test",
         "main.cpp", "handlers.cpp", "db.cpp"],
        cwd=SERVER_DIR, check=True
    )
    print("[build] compiling client...")
    subprocess.run(
        ["g++", "-std=c++20", "-Dlocal_test", "-o", "run_clients", "clients.cpp"],
        cwd=CLIENT_DIR, check=True
    )

# ── server lifecycle ──────────────────────────────────────────────────────────
def start_server():
    p = subprocess.Popen(["./test", "0"], cwd=SERVER_DIR)
    wait_for_ready()
    print(f"[server] started (pid {p.pid})")
    return p

def wait_for_ready(timeout=10):
    for _ in range(timeout * 10):
        try:
            s = socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=1)
            s.close()
            return
        except:
            time.sleep(0.1)
    raise RuntimeError("[server] never came up")

def kill_server(proc):
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    print(f"[server] killed")

# ── client ────────────────────────────────────────────────────────────────────
def start_client():
    p = subprocess.Popen(
        ["./run_clients", str(MIN_ACKS_BEFORE_CRASH)],
        cwd=CLIENT_DIR
    )
    print(f"[client] started (pid {p.pid})")
    return p

def wait_for_sentinel(timeout=30):
    for _ in range(timeout * 10):
        if os.path.exists(SENTINEL):
            return
        time.sleep(0.1)
    raise RuntimeError("[sentinel] timed out waiting for ready_to_crash")

# ── expected state ────────────────────────────────────────────────────────────
def compute_expected(global_wal_path):
    # replay global_wal — highest log_index per key wins
    expected  = {}   # k -> v
    best_idx  = {}   # k -> log_index
    with open(global_wal_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 3:
                continue
            k, v, log_idx = parts[0], parts[1], int(parts[2])
            if k not in best_idx or log_idx > best_idx[k]:
                best_idx[k]  = log_idx
                expected[k]  = v
    return expected

# ── TCP read ──────────────────────────────────────────────────────────────────
def send_read(k):
    s = socket.create_connection(("127.0.0.1", SERVER_PORT))
    k_bytes = k.encode()
    s.sendall(bytes([READ_OP]))
    s.sendall(struct.pack("<I", len(k_bytes)))
    s.sendall(k_bytes)
    v_len = struct.unpack("<I", s.recv(4))[0]
    v = s.recv(v_len).decode() if v_len > 0 else ""
    s.close()
    return v

# ── assertions ────────────────────────────────────────────────────────────────
def assert_no_tmp():
    for fname in os.listdir(SNAP_DIR):
        assert not fname.endswith(".tmp"), \
            f"[FAIL] orphaned .tmp found after reboot: {fname}"
    print("[PASS] no orphaned .tmp files")

def assert_one_snap():
    bins = [f for f in os.listdir(SNAP_DIR) if f.endswith(".bin")]
    assert len(bins) <= 1, f"[FAIL] multiple snapshots found: {bins}"
    print(f"[PASS] snapshot count ok ({len(bins)} .bin files)")

def assert_wal_truncated():
    # find latest snap index
    latest = 0
    for fname in os.listdir(SNAP_DIR):
        if fname.startswith("snapshot.") and fname.endswith(".bin"):
            idx = int(fname[9:-4])
            latest = max(latest, idx)

    if latest == 0:
        print("[PASS] WAL truncation skipped — no snapshot taken yet")
        return

    with open(WAL_PATH) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            idx = int(parts[2])
            assert idx >= latest, \
                f"[FAIL] WAL has entry {idx} below snap index {latest}"
    print(f"[PASS] WAL properly truncated (all entries >= snap {latest})")

def assert_db_state(expected):
    print(f"[verify] checking {len(expected)} keys...")
    for k, v in expected.items():
        actual = send_read(k)
        assert actual == v, \
            f"[FAIL] key {k}: expected {v} got {actual}"
    print(f"[PASS] all {len(expected)} keys match expected state")

# ── cleanup ───────────────────────────────────────────────────────────────────
def cleanup():
    if os.path.exists(SNAP_DIR):    # ← add this guard
        for fname in os.listdir(SNAP_DIR):
            os.remove(os.path.join(SNAP_DIR, fname))
    if os.path.exists(WAL_PATH):
        os.remove(WAL_PATH)
    if os.path.exists(GLOBAL_WAL):
        os.remove(GLOBAL_WAL)
    if os.path.exists(SENTINEL):
        os.remove(SENTINEL)
    print("[cleanup] done")

# ── main ──────────────────────────────────────────────────────────────────────
def run_crash_test():
    print("\n=== CRASH TEST ===\n")

    cleanup()
    build()

    # start server
    server = start_server()

    # start client — spams writes, signals when MIN_ACKS_BEFORE_CRASH hit
    client = start_client()

    # wait for sentinel — client has committed enough writes
    wait_for_sentinel()
    print("[sentinel] ready_to_crash received")

    # crash server while writes still in flight
    kill_server(server)

    # client will error out naturally — wait for it
    client.wait()

    # compute expected state from global_wal dumped before crash
    expected = compute_expected(GLOBAL_WAL)
    print(f"[expected] {len(expected)} unique keys committed before crash")

    # reboot
    print("[reboot] starting server...")
    server = start_server()

    # verify
    assert_no_tmp()
    assert_one_snap()
    assert_wal_truncated()
    assert_db_state(expected)

    kill_server(server)
    time.sleep(1)

    print("[wal] post-crash contents:")
    with open(WAL_PATH) as f:
        for line in f:
            print(" ", line.strip())

    print("\n=== CRASH TEST PASSED ===\n")

if __name__ == "__main__":
    run_crash_test()