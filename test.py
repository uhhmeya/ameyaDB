import asyncio
import json
from datetime import datetime
import websockets
import client

RELAY_WS_URL = "ws://127.0.0.1:8765"

NUM_NODES     = 5
NUM_CLIENTS   = 10

DOWNTIME_SECS = 15 # how long node should stay dead
SETTLE_SECS   = 20 # how long cluster should be given grace to find new leader

relay_ws = None
revived = []

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)

# sends to relay. relay forwards to node
async def send_to_node(node_id, text):
    await relay_ws.send(json.dumps({"to": node_id, "msg": text}))


async def wake_cluster():
    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "connect all")


# the relay sends {"revived": n} when node n says hello again after being terminated
async def watch_relay():
    async for raw in relay_ws:
        msg = json.loads(raw)
        if "revived" in msg:
            revived[msg["revived"]].set()


async def test():
    log("starting test...")
    await wake_cluster()
    await asyncio.sleep(10)
    client.start_clients(NUM_CLIENTS)
    await asyncio.sleep(10)

    for node_id in range(NUM_NODES):
        log(f"node{node_id} down for {DOWNTIME_SECS}s")
        await send_to_node(node_id, f"terminate {DOWNTIME_SECS}")
        await revived[node_id].wait()
        await send_to_node(node_id, "connect all")

        await asyncio.sleep(SETTLE_SECS)

    log("all nodes cycled, draining")
    await asyncio.sleep(10)


async def main():

    # connect to relay
    global relay_ws
    async with websockets.connect(RELAY_WS_URL) as conn:
        relay_ws = conn

        for _ in range(NUM_NODES):
            revived.append(asyncio.Event())

        watcher = asyncio.create_task(watch_relay())
        try:
            await test()
        finally:
            watcher.cancel()
            client.stop_clients()

    log("done")


if __name__ == "__main__":
    asyncio.run(main())