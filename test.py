import asyncio
import json
import random
import struct
import websockets

RELAY_WS_URL = "ws://127.0.0.1:8765"

NUM_NODES     = 5
NUM_CLIENTS   = 10

DOWNTIME_SECS = 15 # how long node should stay dead
SETTLE_SECS   = 20 # how long cluster should be given grace to find new leader

# client --> node
CLIENT_PORT = 7000
OP_WR = 1
I_AM_LEADER, I_AM_NOT_LEADER, IDK = 1, 2, 3

relay_ws = None
revive_flags = []

# when true, clients stop sending writes
test_over = False

# testy --> relay --> node
async def send_to_node(node_id, text):
    await relay_ws.send(json.dumps({"to": node_id, "msg": text}))

async def raise_flags():
    async for raw in relay_ws:
        msg = json.loads(raw)
        if "revived" in msg:
            revive_flags[msg["revived"]].set()

def build_write(key, val):
    key, val = key.encode(), val.encode()
    return bytes([OP_WR]) + struct.pack("<I", len(key)) + key + struct.pack("<I", len(val)) + val



async def run_client(client_id):
    guess = random.randrange(NUM_NODES)
    write_number = 0

    while not test_over:
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(f"node-{guess}.ameyadb.internal", CLIENT_PORT), timeout=2)

            # send writes to leader
            while not test_over:
                writer.write(build_write(f"c{client_id}-k{write_number}", f"v{write_number}"))
                reply = await asyncio.wait_for(reader.readexactly(5), timeout=5)
                is_leader, leader = struct.unpack("<Bi", reply)
                if is_leader == I_AM_LEADER:
                    write_number += 1

                # find leader
                else:
                    guess = leader if is_leader == I_AM_NOT_LEADER else random.randrange(NUM_NODES)
                    break

        # find leader
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            guess = random.randrange(NUM_NODES)

        # hang up, and pause so we don't spam reconnects during an election
        if writer:
            writer.close()
        await asyncio.sleep(0.05)


async def run():
    global test_over
    print("starting test...", flush=True)

    # wake up cluster
    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "connect all")
    await asyncio.sleep(5)

    clients = [asyncio.create_task(run_client(client_id)) for client_id in range(NUM_CLIENTS)]
    await asyncio.sleep(5)

    for node_id in range(NUM_NODES):
        await send_to_node(node_id, f"terminate {DOWNTIME_SECS}") # terminate node
        await revive_flags[node_id].wait() # wait for revive
        await send_to_node(node_id, "connect all") # tell it to rejoin cluster
        await asyncio.sleep(SETTLE_SECS) # wait for cluster to settle

    print("all nodes cycled, draining", flush=True)
    await asyncio.sleep(10)

    # stop clients and wait for them to finish
    test_over = True
    await asyncio.gather(*clients)


async def main():
    global relay_ws

    # connect to relay
    relay_ws = await websockets.connect(RELAY_WS_URL)

    # create revive_flags array
    for _ in range(NUM_NODES):
        revive_flags.append(asyncio.Event())

    # notice when flags are raised
    watcher = asyncio.create_task(raise_flags())

    # run test
    await run()

    # close
    watcher.cancel()
    await relay_ws.close()

    print("done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())