import asyncio
import json
from datetime import datetime

import websockets

import client

RELAY_WS_URL = "ws://127.0.0.1:8765"

NUM_NODES     = 5
NUM_CLIENTS   = 10
DOWNTIME_SECS = 15   # how long a terminated node stays down
SETTLE_SECS   = 20   # let the cluster re-elect and clients re-find the leader
GIVE_UP_SECS  = 90   # a node that never comes back must not hang the whole test

relay_ws = None
born_dead = []       # one Event per node, set when it reconnects to the relay

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)

# sends to relay. relay forwards to node
async def send_to_node(node_id, text):
    await relay_ws.send(json.dumps({"to": node_id, "msg": text}))


async def wake_cluster():
    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "connect all")


# the relay sends {"born_dead": n} the moment node n reconnects to it
async def watch_relay():
    async for raw in relay_ws:
        msg = json.loads(raw)
        if "born_dead" in msg:
            born_dead[msg["born_dead"]].set()


async def wait_until_born_dead(node_id):
    # the relay prints "nodeN born dead" itself, so don't say it twice
    try:
        await asyncio.wait_for(born_dead[node_id].wait(), GIVE_UP_SECS)
    except asyncio.TimeoutError:
        log(f"node{node_id} never came back -- moving on")


async def test():
    log("starting test...")
    await wake_cluster()
    await asyncio.sleep(10)
    client.start_clients(NUM_CLIENTS)
    await asyncio.sleep(10)

    for node_id in range(NUM_NODES):
        log(f"node{node_id} down for {DOWNTIME_SECS}s")
        born_dead[node_id].clear()
        await send_to_node(node_id, f"terminate {DOWNTIME_SECS}")
        await wait_until_born_dead(node_id)
        await send_to_node(node_id, "connect all")

        await asyncio.sleep(SETTLE_SECS)

    log("all nodes cycled, draining")
    await asyncio.sleep(10)


async def main():
    global relay_ws
    async with websockets.connect(RELAY_WS_URL) as conn:
        relay_ws = conn

        for _ in range(NUM_NODES):
            born_dead.append(asyncio.Event())

        watcher = asyncio.create_task(watch_relay())
        try:
            await test()
        finally:
            watcher.cancel()
            client.stop_clients()

    log("done")


if __name__ == "__main__":
    asyncio.run(main())