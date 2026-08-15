import os
import signal
import subprocess
import time
from datetime import datetime

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")

# ./ameyaDB
ROOT = os.path.dirname(os.path.abspath(__file__))

SERVER_DIR = os.path.join(ROOT, "engine/src/server")
OUTPUT_DIR = os.path.join(ROOT, "engine/src/output")
SNAP_DIR   = os.path.join(OUTPUT_DIR, "snaps")
WAL_PATH   = os.path.join(OUTPUT_DIR, "wal.txt")
EXEC_DIR   = os.path.join(OUTPUT_DIR, "EXEC")
SERVER_EXEC_PATH = os.path.join(EXEC_DIR, "server")
CLIENT_EXEC_PATH = os.path.join(EXEC_DIR, "client")
DEBUG_DIR  = os.path.join(ROOT, "engine/debug")

NUM_NODES = 5
SERVER_PORTS = [8080 + i for i in range(NUM_NODES)]

def remove_stale():

    # stale execs from a previous run
    for exe in (SERVER_EXEC_PATH, CLIENT_EXEC_PATH):
        if os.path.exists(exe):
            os.remove(exe)

    # stale servers still holding any of the NUM_NODES ports
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

    # stale debug logs
    if os.path.exists(DEBUG_DIR):
        for file in os.listdir(DEBUG_DIR):
            os.remove(os.path.join(DEBUG_DIR, file))
    else:
        os.makedirs(DEBUG_DIR)

def main():
    print("\n\n")
    remove_stale()

    # compile server
    subprocess.run(
        ["g++", "-std=c++20", "-o", SERVER_EXEC_PATH,
         "main.cpp", "handlers.cpp", "walsnap.cpp", "threads.cpp"],
        cwd=SERVER_DIR, check=True
    )


    # maps node to log file
    log_files = [
        open(os.path.join(DEBUG_DIR, f"node{i}.log"), "w") for i in range(NUM_NODES)]

    # creates process
    servers = [
        subprocess.Popen([SERVER_EXEC_PATH, str(i), "127.0.0.1"], stdout=log_files[i], stderr=subprocess.STDOUT, cwd=SERVER_DIR)
        for i in range(NUM_NODES)
    ]

    RUN_SECONDS = 30
    time.sleep(RUN_SECONDS)

    # terminate process
    for s in servers:
        s.send_signal(signal.SIGKILL)
        s.wait()
    for f in log_files:
        f.close()

    log("all servers terminated\n\n")

if __name__ == "__main__":
    main()