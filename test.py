import asyncio
import json
from datetime import datetime

import websockets

import client

RELAY_WS_URL = "ws://127.0.0.1:8765"

NUM_NODES     = 5
NUM_CLIENTS   = 10
DOWNTIME_SECS = 15   # how long a terminated node stays down
REJOIN_GRACE  = 8    # crash.sh needs a beat past its sleep to restart + redial
SETTLE_SECS   = 20   # let the cluster re-elect and clients re-find the leader

relay_ws = None

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)

# sends to relay. relay forwards to node
async def send_to_node(node_id, text):
    await relay_ws.send(json.dumps({"to": node_id, "msg": text}))


async def wake_whole_cluster():
    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "connect all")


async def chaos_scenario():
    log("[chaos] waking cluster")
    await wake_whole_cluster()
    await asyncio.sleep(10)

    log(f"[chaos] starting {NUM_CLIENTS} clients -- writes flow from here on")
    client.start_clients(NUM_CLIENTS)
    await asyncio.sleep(10)          # baseline before anything breaks

    for node_id in range(NUM_NODES):
        log(f"[chaos] ---- terminating node {node_id} for {DOWNTIME_SECS}s ----")
        await send_to_node(node_id, f"terminate {DOWNTIME_SECS}")
        await asyncio.sleep(DOWNTIME_SECS + REJOIN_GRACE)

        log(f"[chaos] node {node_id} should be back -- re-arming whole cluster")
        await wake_whole_cluster()
        await asyncio.sleep(SETTLE_SECS)

    log("[chaos] all nodes cycled, draining")
    await asyncio.sleep(10)


async def main():
    global relay_ws
    async with websockets.connect(RELAY_WS_URL) as conn:
        relay_ws = conn
        try:
            await chaos_scenario()
        finally:
            client.stop_clients()
    log("[chaos] done")


if __name__ == "__main__":
    asyncio.run(main())