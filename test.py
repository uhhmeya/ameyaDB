#!/usr/bin/env python3
import os
import signal
import socket
import struct
import subprocess
import time

SERVER_DIR = "engine/src/server"
CLIENT_DIR = "engine/src"
SNAP_DIR   = "engine/src/output/snaps"
WAL_PATH   = "engine/src/output/wal.txt"
ACK_PATH   = "engine/src/output/acks.txt"
SENTINEL   = "engine/src/output/crash"

SERVER_PORT = 8080
MIN_ACKS_BEFORE_CRASH = 15000

READ_OP = 2

def start_local_server(timeout=10):
    p = subprocess.Popen(["../output/binary/server_exec", "0"], cwd=SERVER_DIR)
    for _ in range(timeout * 10):
        if p.poll() is not None:
            raise RuntimeError(f"[server] exited early with code {p.returncode}")
        try:
            s = socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=1)
            s.close()
            print(f"[server] started (pid {p.pid})")
            return p
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("[server] never came up")

def crash_local_server(proc):
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    print(f"[server] killed")

def start_local_clients():
    p = subprocess.Popen(
        ["./output/binary/local_clients_exec", str(MIN_ACKS_BEFORE_CRASH)],
        cwd="engine/src"
    )
    print(f"[client] started (pid {p.pid})")
    return p

def compute_expected(global_wal_path):
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

def assert_no_tmp():
    for fname in os.listdir(SNAP_DIR):
        assert not fname.endswith(".tmp"), \
            f"[FAIL] orphaned .tmp found after reboot: {fname}"
    print("[PASS] no orphaned .tmp files")

def assert_one_snap():
    snaps = [f for f in os.listdir(SNAP_DIR) if f.endswith(".txt")]
    assert len(snaps) <= 1, f"[FAIL] multiple snapshots found: {snaps}"

def assert_wal_truncated():
    latest = 0
    for fname in os.listdir(SNAP_DIR):
        if fname.startswith("snap") and fname.endswith(".txt"):
            idx = int(fname[5:-4])
            latest = max(latest, idx)
    if latest == 0:
        return
    with open(WAL_PATH) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            idx = int(parts[2])
            assert idx >= latest, f"[FAIL] WAL has entry {idx} below snap index {latest}"

def assert_db_state(expected):
    for k, v in expected.items():
        actual = send_read(k)
        assert actual == v, \
            f"[FAIL] key {k}: expected {v} got {actual}"


def main():

    # clear zombies
    zombie = subprocess.run(["lsof", "-t", f"-i:{SERVER_PORT}"], capture_output=True, text=True)
    for pid in zombie.stdout.strip().splitlines():
        os.kill(int(pid), signal.SIGKILL)
        print(f" [test.py -> main] removed zombie({pid})")

    # remove old files (does not delete directories)
    if os.path.exists(SNAP_DIR):
        for file in os.listdir(SNAP_DIR): os.remove(os.path.join(SNAP_DIR, file))
    if os.path.exists(WAL_PATH): os.remove(WAL_PATH)
    if os.path.exists(ACK_PATH): os.remove(ACK_PATH)
    if os.path.exists(SENTINEL): os.remove(SENTINEL)

    # will work on other machines
    OUTPUT = os.path.abspath("engine/src/output")

    # compiles local server ; wd = src.server
    subprocess.run(
        ["g++", "-std=c++20", "-Dlocal_test", "-o",
         f"{OUTPUT}/binary/server_exec",
         "main.cpp", "handlers.cpp", "db.cpp"],
        cwd="engine/src/server", check=True
    )

    # compiles client ; wd = src
    subprocess.run(
        ["g++", "-std=c++20", "-Dlocal_test", "-o",
         f"{OUTPUT}/binary/local_clients_exec",
         "clients.cpp"],
        cwd="engine/src", check=True
    )

    # start test
    local_server = start_local_server()
    local_client = start_local_clients()

    # find sentinel
    timed_out = True
    for _ in range(300):
        if os.path.exists(SENTINEL):
            timed_out = False
            break
        time.sleep(0.1)
    if timed_out:
        raise RuntimeError("[test.py -> main] sentinel not found after 30s")

    # crash local server
    local_server.send_signal(signal.SIGKILL)

    local_server.wait()
    local_client.wait()

    expected_db = compute_expected(ACK_PATH)

    server = start_local_server()

    assert_no_tmp()
    assert_one_snap()
    assert_wal_truncated()
    assert_db_state(expected_db)

    crash_local_server(server)
    time.sleep(1)

    print("\n=== CRASH TEST PASSED ===\n")

if __name__ == "__main__":
    main()