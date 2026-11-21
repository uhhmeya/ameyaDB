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
I_AM_LEADER = 11
I_AM_NOT_LEADER = 12
IDK = 13

relay_ws = None
born_dead_flags = []
done_flags = []
db_state_flags = []
db_states = {}
is_test_over = False

# testy --> relay --> node
async def send_to_node(node_id, text):
    await relay_ws.send(json.dumps({"to": node_id, "msg": text}))

async def send_to_browser(results):
    await relay_ws.send(json.dumps({"to": "browser", "results": results}))

async def listen_to_relay():
    async for raw in relay_ws:
        msg = json.loads(raw)

        if "born_dead" in msg:
            await send_to_node(msg["born_dead"], "connect all")
            born_dead_flags[msg["born_dead"]].set()

        elif "done" in msg:
            done_flags[msg["done"]].set()

        elif "agreement_check_res" in msg:
            db_states[msg["node"]] = msg["agreement_check_res"]
            db_state_flags[msg["node"]].set()

def encode_write(key, val):
    key, val = key.encode(), val.encode()
    return bytes([OP_WR]) + struct.pack("<I", len(key)) + key + struct.pack("<I", len(val)) + val

def guess(node_id):
    return f"node-{node_id}.ameyadb.internal"

async def run_client(client_num):

    guess_node = guess(random.randrange(NUM_NODES))
    wr_num = 0

    while not is_test_over:
        writer = None

        try:
            conn = asyncio.open_connection(guess_node, CLIENT_PORT)
            reader, writer = await asyncio.wait_for(conn, timeout=2)

            # send writes to leader
            while not is_test_over:

                key = f"{client_num}_{wr_num}"
                val = f"v{random.randint(1, 999)}"
                writer.write(encode_write(key, val))

                reply = await asyncio.wait_for(reader.readexactly(5), timeout=5)
                leader_status = reply[0]

                if leader_status == I_AM_LEADER:
                    wr_num += 1

                # connect to leader
                elif leader_status == I_AM_NOT_LEADER:
                    leader_id = struct.unpack_from("<i", reply, 1)[0]
                    guess_node = guess(leader_id)
                    break

                else: # idk
                    guess_node = guess(random.randrange(NUM_NODES))
                    break

        # restart while loop
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            guess_node = guess(random.randrange(NUM_NODES))

        finally:

            if writer:
                writer.close()
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
        born_dead_flags[node_id].clear()
        await send_to_node(node_id, "terminate 15")
        await born_dead_flags[node_id].wait()
        await asyncio.sleep(10) # settle

    await asyncio.sleep(3)

    # stop clients and wait for them to finish
    is_test_over = True
    await asyncio.gather(*clients)

    await check_agreement()

async def wait_for_all(flags, timeout):
    try: await asyncio.wait_for(asyncio.gather(*[flag.wait() for flag in flags]), timeout)
    except asyncio.TimeoutError: pass

async def check_agreement():

    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "writes_stopped")
    await wait_for_all(done_flags, 30)

    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "agreement_check_req")
    await wait_for_all(db_state_flags, 10)

    nodes = []
    digests = set()
    for node_id in range(NUM_NODES):
        if node_id in db_states:
            commit_idx, term, num_keys, digest = db_states[node_id].split()
            nodes.append({"commit_idx": int(commit_idx), "term": int(term)})
            digests.add(digest)
        else:
            nodes.append(None)

    agree = len(db_states) == NUM_NODES and len(digests) == 1
    await send_to_browser({"nodes": nodes, "agree": agree})

async def main():
    global relay_ws

    # connect to relay
    relay_ws = await websockets.connect(RELAY_WS_URL)
    await relay_ws.send(json.dumps({"to": "relay", "msg": "i am testy"}))

    # create flags
    for _ in range(NUM_NODES):
        born_dead_flags.append(asyncio.Event())
        done_flags.append(asyncio.Event())
        db_state_flags.append(asyncio.Event())

    # listen to relay
    watcher = asyncio.create_task(listen_to_relay())

    # run test
    await run()

    # close
    watcher.cancel()
    await relay_ws.close()

    print("done", flush=True)

if __name__ == "__main__":
    asyncio.run(main())