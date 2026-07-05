import os
import signal
import socket
import struct
import subprocess
import time

# ./ameyaDB
ROOT = os.path.dirname(os.path.abspath(__file__))

SERVER_DIR = os.path.join(ROOT, "engine/src/server")
CLIENT_DIR = os.path.join(ROOT, "engine/src")
OUTPUT_DIR = os.path.join(ROOT, "engine/src/output")
SNAP_DIR   = os.path.join(OUTPUT_DIR, "snaps")
WAL_PATH   = os.path.join(OUTPUT_DIR, "wal.txt")
EXEC_DIR   = os.path.join(OUTPUT_DIR, "EXEC")
SERVER_EXEC_PATH = os.path.join(EXEC_DIR, "server")
CLIENT_EXEC_PATH = os.path.join(EXEC_DIR, "client")


SERVER_PORT = 8080
spam_time_sec = 5
READ_OP = 2
passed = True

def start_server(timeout=10):

    # path vars in server code are relative to src/server
    p = subprocess.Popen([SERVER_EXEC_PATH, "0"], cwd=SERVER_DIR)

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

    # remove stale execs
    for exe in (SERVER_EXEC_PATH, CLIENT_EXEC_PATH):
        if os.path.exists(exe):
            os.remove(exe)

    # remove stale server
    stale_server = subprocess.run(["lsof", "-t", f"-i:{SERVER_PORT}"], capture_output=True, text=True)
    for pid in stale_server.stdout.strip().splitlines():
        os.kill(int(pid), signal.SIGKILL)
        print(f"[test -> main] removed stale server({pid})")

    # remove stale snap.txt
    if os.path.exists(SNAP_DIR):
        for file in os.listdir(SNAP_DIR):
            os.remove(os.path.join(SNAP_DIR, file))

    # remove stale wal.txt
    if os.path.exists(WAL_PATH):
        os.remove(WAL_PATH)


    # compiles server
    subprocess.run(
        ["g++", "-std=c++20", "-o", SERVER_EXEC_PATH, "main.cpp", "handlers.cpp", "walsnap.cpp"],
        cwd=SERVER_DIR, check=True
    )

    # compiles client
    subprocess.run(
        ["g++", "-std=c++20", "-o", CLIENT_EXEC_PATH, "clients.cpp"],
        cwd=CLIENT_DIR, check=True
    )

    # make server process ; path vars are relative to src/server
    server = start_server()
    print(f"[test] server {server.pid} started")

    # make client process ; there are no path vars in clients.cpp
    client = subprocess.Popen([CLIENT_EXEC_PATH])
    print(f"[test] client {client.pid} started")

    # let client spam writes to server for 5s
    time.sleep(spam_time_sec)

    # freeze server
    server.send_signal(signal.SIGSTOP)
    print(f"[test] server {server.pid} frozen")

    exp = {}

    # capture db state
    with open(os.path.join(SNAP_DIR, "snap")) as snap:
        idx_dur_snap = int(snap.readline().strip())
        for entry in snap:
            k, v = entry.strip().split()
            exp[k] = v
    with open(WAL_PATH) as wal:
        for entry in wal:
            parts = entry.strip().split()
            if len(parts) < 8: continue
            k, v, log_idx = parts[0], parts[1], int(parts[5])
            if log_idx > idx_dur_snap:
                exp[k] = v

    # terminate server & client
    server.send_signal(signal.SIGKILL)
    server.wait()
    print(f"[test] server {server.pid} terminated")
    client.send_signal(signal.SIGKILL)
    client.wait()
    print(f"[test] client {client.pid} terminated")

    # reboot server
    reboot = start_server()
    print(f"[test] server {reboot.pid} started")

    # verify wal recovery
    with open(WAL_PATH) as WAL:
        for entry in WAL:
            parts = entry.strip().split()
            if len(parts) < 8: continue # partial
            wal_entry_idx = int(parts[5])
            if wal_entry_idx < idx_dur_snap:
                print(f"[test] ERROR wal entry({wal_entry_idx}) below snap index({idx_dur_snap})")
                passed = False

    # verify db state recovery
    bad = 0
    for k, exp_v in exp.items():
        actual_v = send_read(k)
        if actual_v != exp_v:
            bad += 1
            passed = False

    # terminate server
    reboot.send_signal(signal.SIGKILL)
    reboot.wait()
    print(f"[test] server {reboot.pid} terminated")

    if passed :
        print("crash test passed \n\n")

    else :
        print("crash test failed \n\n")


if __name__ == "__main__":
    main()