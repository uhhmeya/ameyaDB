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

SERVER_PORT = 8080
spam_time_sec = 5
READ_OP = 2
passed = True

def start_local_server(timeout=10):
    p = subprocess.Popen(["../output/binary/server_exec", "0"], cwd=SERVER_DIR)
    for _ in range(timeout * 10):
        if p.poll() is not None:
            raise RuntimeError(f"[server] exited early with code {p.returncode}")
        try:
            s = socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=1)
            s.close()
            return p
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("[server] never came up")

def start_local_clients():
    return subprocess.Popen(
        ["./output/binary/local_clients_exec"],
        cwd="engine/src"
    )

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

def main():
    print("\n\n")
    global passed

    # clear zombies
    zombie = subprocess.run(["lsof", "-t", f"-i:{SERVER_PORT}"], capture_output=True, text=True)
    for pid in zombie.stdout.strip().splitlines():
        os.kill(int(pid), signal.SIGKILL)
        print(f"[test -> main] removed zombie({pid})")

    # remove old files
    if os.path.exists(SNAP_DIR):
        for file in os.listdir(SNAP_DIR): os.remove(os.path.join(SNAP_DIR, file))
    if os.path.exists(WAL_PATH): os.remove(WAL_PATH)

    OUTPUT = os.path.abspath("engine/src/output")

    # server ; wd = src.server
    subprocess.run(
        ["g++", "-std=c++20", "-Dlocal_test", "-o",
         f"{OUTPUT}/binary/server_exec",
         "main.cpp", "handlers.cpp", "walsnap.cpp"],
        cwd="engine/src/server", check=True
    )

    # client ; wd = src
    subprocess.run(
        ["g++", "-std=c++20", "-Dlocal_test", "-o",
         f"{OUTPUT}/binary/local_clients_exec",
         "clients.cpp"],
        cwd="engine/src", check=True
    )

    local_server = start_local_server()
    print(f"[test] server {local_server.pid} started")
    local_client = start_local_clients()
    print(f"[test] client {local_client.pid} started")

    time.sleep(spam_time_sec)
    local_server.send_signal(signal.SIGSTOP)
    print(f"[test] server {local_server.pid} frozen")

    exp = {}

    with open(os.path.join(SNAP_DIR, "snap")) as snap:
        idx_dur_snap = int(snap.readline().strip())
        for entry in snap:
            x = entry.strip().split()
            exp[x[0]] = x[1]

    with open(WAL_PATH) as wal:
        for entry in wal:
            parts = entry.strip().split()
            if len(parts) < 3: continue
            k, v, log_idx = parts[0], parts[1], int(parts[2])
            if log_idx > idx_dur_snap:
                exp[k] = v

    local_server.send_signal(signal.SIGKILL)
    local_server.wait()
    print(f"[test] server {local_server.pid} terminated")
    local_client.send_signal(signal.SIGKILL)
    local_client.wait()
    print(f"[test] client {local_client.pid} terminated")

    reboot = start_local_server()
    print(f"[test] server {reboot.pid} started")

    with open(WAL_PATH) as WAL:
        for entry in WAL:
            parts = entry.strip().split()
            if len(parts) < 3: continue # partial
            wal_entry_idx = int(parts[2])
            if wal_entry_idx < idx_dur_snap:
                print(f"[test] ERROR wal entry({wal_entry_idx}) below snap index({idx_dur_snap})")
                passed = False

    bad = 0
    for k, exp_v in exp.items():
        actual_v = send_read(k)
        if actual_v != exp_v:
            bad += 1
            passed = False
    print(f"[test] {bad}/{len(exp)} keys had wrong value")


    reboot.send_signal(signal.SIGKILL)
    reboot.wait()
    print(f"[test] server {reboot.pid} terminated")

    if passed :
        print("crash test passed")

    else :
        print("crash test failed\n\n")


if __name__ == "__main__":
    main()