import asyncio
import json
from datetime import datetime

import websockets

# relay.py is the one who spawns test.py, so the relay is always on this machine
RELAY_WS = "ws://127.0.0.1:8765"

NUM_NODES = 5

# websocket to the relay, set once in main()
relay = None

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")

# every command is one envelope: {"to": node, "msg": text}
# relay unwraps it and writes "text\n" onto that node's TCP wire
async def send(node, text):
    await relay.send(json.dumps({"to": node, "msg": text}))
    log(f"[test] node{node} <- {text}")

# peers is "all" or a digit string like "023"
# "connect all" -> node connects to every node
# "connect 023" -> node connects to nodes 0, 2, 3 only
async def connect(node, peers):
    await send(node, f"connect {peers}")

# node terminates itself
async def terminate(node):
    await send(node, "terminate")

async def scenario():

    # wake the whole cluster into a full mesh
    for n in range(NUM_NODES):
        await connect(n, "all")
    await asyncio.sleep(10)

    # kill node 4 outright
    await terminate(4)
    await asyncio.sleep(5)

    # partition node 0: it may only talk to 1 and 2 now
    await connect(0, "12")
    await asyncio.sleep(10)

async def main():
    global relay
    async with websockets.connect(RELAY_WS) as ws:
        relay = ws
        await scenario()
    log("[test] scenario done")

if __name__ == "__main__":
    asyncio.run(main())