import asyncio
import json
from datetime import datetime

import websockets

# relay.py is the one who spawns test.py, so the relay is always on this machine
TEST_TO_RELAY_WS = "ws://127.0.0.1:8765"

NUM_NODES = 5

# websocket to the relay, set once in main()
test_to_relay_ws = None

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")

# {"to": node, "msg": text}
async def send(node, text):
    await test_to_relay_ws.send(json.dumps({"to": node, "msg": text}))

async def scenario():

    # wake cluster
    for n in range(NUM_NODES):
        await send(n, "connect all")
    await asyncio.sleep(10)

    # terminate 1 node
    # wait for it to come back up
    # let it connect to all other nodes
    # repeat for all nodes
    for n in range(NUM_NODES):
        await send(n, "terminate")
        await asyncio.sleep(5)
        await send(n, "connect all")
        await asyncio.sleep(10)

async def main():
    global test_to_relay_ws
    async with websockets.connect(TEST_TO_RELAY_WS) as ws:
        test_to_relay_ws = ws
        await scenario()
    log("[test] scenario done")

if __name__ == "__main__":
    asyncio.run(main())