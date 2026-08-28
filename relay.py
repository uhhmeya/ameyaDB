import asyncio
import websockets
import os
import json
from datetime import datetime
import re

# any computer can connect
TCP_HOST = "0.0.0.0"
WS_HOST = "0.0.0.0"

# nodes send msg to 9000
# relay reads msg from 9000
TCP_PORT = 9000

# relay & browser talk over socket
# socket is built over port 8765
WS_PORT = 8765

# browser is not connected yet
browser = None

# node_id -> TCP writer, so the relay can talk BACK to a node later (wake / die)
nodes = {}

# node_id -> how many times it has said hello (its rebirth generation)
hellos = {}

fd_parser = re.compile(r"\(node (\d+)\)")

SLEEP_THRESHOLD = 60 # seconds

# a dead node must say hello again within this window -- the tests count on
# nodes coming back at a proper time. NOTE: today systemd re-clones + rebuilds
# on every restart (RestartSec=15 + ExecStartPre build), so rebirth is slow --
# tune this to what you actually measure.
REBIRTH_DEADLINE = 120 # seconds

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")


async def run_test():
    proc = await asyncio.create_subprocess_exec("python3", "test.py",)
    returncode = await proc.wait()
    log(f"test.py exited with code {returncode}")

async def send_to_browser(msg):
    if browser is None:
        print(f"FATAL: No browser connected relay dropped msg : {msg}")
        os._exit(1)
    try:
        await browser.send(msg)
    except websockets.exceptions.ConnectionClosed:
        print("FATAL: browser connection closed mid-send")
        os._exit(1)

# tells the browser which nodes are currently connected (== born dead until woken)
async def send_roster():
    await send_to_browser(json.dumps({"type": "roster", "nodes": sorted(nodes.keys())}))

# a node just went down -- if it is not born dead again in time, scream.
# `seen` pins the rebirth generation at the moment of death, so a node that
# came back and died AGAIN is judged by its own newer deadline, not this one.
async def expect_rebirth(node_id, seen):
    await asyncio.sleep(REBIRTH_DEADLINE)
    if node_id not in nodes and hellos.get(node_id, 0) == seen:
        print(f"FATAL: node{node_id} was not born dead again within {REBIRTH_DEADLINE}s")
        os._exit(1)

def parseFD(msg, writer):
    m = fd_parser.search(msg)
    if not m:
        return None
    node_id = int(m.group(1))
    nodes[node_id] = writer
    hellos[node_id] = hellos.get(node_id, 0) + 1
    log(f"node{node_id} is idle and connected to relay")
    return node_id

# reader receives bytes from wire
# writer sends bytes into wire
async def on_TCP(reader, writer):

    node_id = None
    try:

        # extract line from TCP
        while True:
            raw = await reader.readline()
            if not raw:
                break

            # str(msg)
            msg = raw.decode("utf-8", errors="replace").rstrip("\n")
            if not msg:
                continue

            # who are we talking to?
            if node_id is None:
                node_id = parseFD(msg, writer)
                if node_id is not None:
                    await send_roster()

            await send_to_browser(msg)

    # when tcp wire breaks
    finally:
        # only forget the node if this wire is still the one on record --
        # a reborn node may have registered a fresh wire before the old one
        # timed out (same idea as compare_exchange_strong(stale, -1) in main.cpp)
        if node_id is not None and nodes.get(node_id) is writer:
            del nodes[node_id]
            log(f"node{node_id} unreachable")
            await send_roster()
            asyncio.create_task(expect_rebirth(node_id, hellos.get(node_id, 0)))
        writer.close()

# called when browser connects to relay
async def on_WS(websocket):
    global browser
    browser = websocket
    conn_id = websocket.remote_address[1]
    log(f"relay & browser are connected")

    # a fresh browser (or a refresh) needs to know who is already here
    await send_roster()

    try:
        async for raw in websocket:
            msg = json.loads(raw)["msg"]
            if msg == "run_test.py":
                asyncio.create_task(run_test())

    except websockets.exceptions.ConnectionClosed:
        log(f"browser ({conn_id}) disconnected")

    return

async def main():

    # port 9000 stays closed until the browser is attached --
    # a node can never say hello to a relay that has no browser
    async with websockets.serve(on_WS, WS_HOST, WS_PORT):
        while browser is None:
            await asyncio.sleep(0.2)

        # calls on_TCP() everytime node connects to relay
        tcp_server = await asyncio.start_server(on_TCP, TCP_HOST, TCP_PORT)
        async with tcp_server:
            await tcp_server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())