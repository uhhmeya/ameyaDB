import asyncio
import json
import websockets
import client

RELAY_WS_URL = "ws://127.0.0.1:8765"

NUM_NODES     = 5
NUM_CLIENTS   = 10

DOWNTIME_SECS = 15 # how long node should stay dead
SETTLE_SECS   = 20 # how long cluster should be given grace to find new leader

relay_ws = None
revive_flags = []

# testy --> relay --> node
async def send_to_node(node_id, text):
    await relay_ws.send(json.dumps({"to": node_id, "msg": text}))





# the relay sends {"revived": n} when node n says hello again after being terminated
# raise_flags() listens for that and raises node n's flag so test() knows it's back
async def raise_flags():
    async for raw in relay_ws:
        msg = json.loads(raw)
        if "revived" in msg:
            revive_flags[msg["revived"]].set()


async def test():
    print("starting test...", flush=True)

    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "connect all")
    await asyncio.sleep(10)

    client.start_clients(NUM_CLIENTS)
    await asyncio.sleep(10)

    for node_id in range(NUM_NODES):
        print(f"node{node_id} down for {DOWNTIME_SECS}s", flush=True)
        await send_to_node(node_id, f"terminate {DOWNTIME_SECS}")
        await revive_flags[node_id].wait()
        await send_to_node(node_id, "connect all")

        await asyncio.sleep(SETTLE_SECS)

    print("all nodes cycled, draining", flush=True)
    await asyncio.sleep(10)


async def main():

    # connect to relay
    global relay_ws
    async with websockets.connect(RELAY_WS_URL) as conn:
        relay_ws = conn

        # create revive_flags array
        for _ in range(NUM_NODES):
            revive_flags.append(asyncio.Event())

        # notice when flags are raised
        watcher = asyncio.create_task(raise_flags())

        await test()
        watcher.cancel()
        client.stop_clients()

    print("done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())