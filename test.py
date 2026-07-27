import os
import signal
import subprocess
import time

# ./ameyaDB
ROOT = os.path.dirname(os.path.abspath(__file__))

SERVER_DIR = os.path.join(ROOT, "engine/src/server")
OUTPUT_DIR = os.path.join(ROOT, "engine/src/output")
SNAP_DIR   = os.path.join(OUTPUT_DIR, "snaps")
WAL_PATH   = os.path.join(OUTPUT_DIR, "wal.txt")
EXEC_DIR   = os.path.join(OUTPUT_DIR, "EXEC")
SERVER_EXEC_PATH = os.path.join(EXEC_DIR, "server")
CLIENT_EXEC_PATH = os.path.join(EXEC_DIR, "client")

SERVER_PORTS = [8080, 8081, 8082]

def remove_stale():

    # stale execs from a previous run
    for exe in (SERVER_EXEC_PATH, CLIENT_EXEC_PATH):
        if os.path.exists(exe):
            os.remove(exe)

    # stale servers still holding any of the 3 ports
    for port in SERVER_PORTS:
        stale_server = subprocess.run(["lsof", "-t", f"-i:{port}"], capture_output=True, text=True)
        for pid in stale_server.stdout.strip().splitlines():
            os.kill(int(pid), signal.SIGKILL)
            print(f"[test -> remove_stale] removed stale server({pid}) on port {port}")

    # stale snapshot files
    if os.path.exists(SNAP_DIR):
        for file in os.listdir(SNAP_DIR):
            os.remove(os.path.join(SNAP_DIR, file))

    # stale WAL
    if os.path.exists(WAL_PATH):
        os.remove(WAL_PATH)

def main():
    print("\n\n")
    remove_stale()

    # compile server
    subprocess.run(
        ["g++", "-std=c++20", "-o", SERVER_EXEC_PATH,
         "main.cpp", "handlers.cpp", "walsnap.cpp", "raft.cpp"],
        cwd=SERVER_DIR, check=True
    )

    # boot all nodes
    servers = [subprocess.Popen([SERVER_EXEC_PATH, str(i)], cwd=SERVER_DIR) for i in range(3)]
    print(f"[test] servers started: {[s.pid for s in servers]}\n")

    time.sleep(3)

    for s in servers:
        s.send_signal(signal.SIGKILL)
        s.wait()
    print("\n[test] all servers terminated")

if __name__ == "__main__":
    main()