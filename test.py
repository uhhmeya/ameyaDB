import asyncio
import json
import random
import struct
import websockets

RELAY_WS_URL = "ws://127.0.0.1:8765"

NUM_NODES     = 5
NUM_CLIENTS   = 10

CLIENT_PORT = 7000
OP_WR = 1
I_AM_LEADER = 1
I_AM_NOT_LEADER = 2
IDK = 3

relay_ws = None
revive_flags = []
is_test_over = False

# testy --> relay --> node
async def send_to_node(node_id, text):
    await relay_ws.send(json.dumps({"to": node_id, "msg": text}))

async def raise_flags():
    async for raw in relay_ws:
        msg = json.loads(raw)
        if "revived" in msg:
            revive_flags[msg["revived"]].set()

def sendWR(key, val):
    key, val = key.encode(), val.encode()
    return bytes([OP_WR]) + struct.pack("<I", len(key)) + key + struct.pack("<I", len(val)) + val

def node_host(node_id):
    return f"node-{node_id}.ameyadb.internal"

async def run_client(cl_num):

    guess_node = node_host(random.randrange(NUM_NODES))
    wr_num = 0

    while not is_test_over:
        WR = None

        try:
            conn = asyncio.open_connection(guess_node, CLIENT_PORT)
            R, WR = await asyncio.wait_for(conn, timeout=2)

            # send writes to leader
            while not is_test_over:

                K = f"{cl_num}_{wr_num}"
                V = f"v{random.randint(1, 999)}"
                WR.write(sendWR(K, V))

                reply = await asyncio.wait_for(R.readexactly(5), timeout=5)
                leader_status = reply[0]

                if leader_status == I_AM_LEADER:
                    wr_num += 1

                # connect to leader
                elif leader_status == I_AM_NOT_LEADER:
                    leader_id = struct.unpack_from("<i", reply, 1)[0]
                    guess_node = node_host(leader_id)
                    break

                else:  # idk (connect to random node)
                    guess_node = node_host(random.randrange(NUM_NODES))
                    break

        # restart while loop
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            guess_node = node_host(random.randrange(NUM_NODES))

        finally:

            if WR:
                WR.close()
            await asyncio.sleep(0.05)

async def run():
    global is_test_over
    print("starting test...", flush=True)

    # wake up cluster
    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "connect all")
    await asyncio.sleep(5)

    # spawn clients
    clients = []
    for client_num in range(NUM_CLIENTS):
        task = asyncio.create_task(run_client(client_num))
        clients.append(task)
    await asyncio.sleep(5)

    for node_id in range(NUM_NODES):
        await send_to_node(node_id, f"terminate 15") # terminate
        await revive_flags[node_id].wait()
        await send_to_node(node_id, "connect all")
        await asyncio.sleep(10) # settle

    await asyncio.sleep(3)

    # stop clients and wait for them to finish
    is_test_over = True
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