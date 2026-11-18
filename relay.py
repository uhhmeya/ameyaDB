import asyncio
import websockets
import json
import time

HOST = "0.0.0.0" # anyone can connect
WS_PORT = 8765 # browser + testy
TCP_PORT = 9000  # nodes
NUM_NODES = 5

# handlers
relay_to_browser_WS = None
relay_to_test_WS = None

nodeFDtable = {}
booted = set()
# dead      : process is not running
# born dead : process is running but the node is not in the cluster
# alive     : node is participating in the cluster
state = {n: "dead" for n in range(NUM_NODES)}

def compute_cluster_status():
    alive = [n for n in state if state[n] == "alive"]
    born_dead = [n for n in state if state[n] == "born dead"]
    dead = [n for n in state if state[n] == "dead"]
    return f"alive {alive} born dead {born_dead} dead {dead}"

async def inform_browser(status):
    try:
        await relay_to_browser_WS.send(json.dumps({"type": "cluster", "msg": status, "wall_us": time.time_ns() // 1000}))
    except websockets.exceptions.ConnectionClosed:
        pass

async def on_node(reader, writer):
    node_id = None
    try:

        # get msg from node
        while True:

            # handle death
            try:
                raw = await reader.readline()
            except ConnectionResetError: raw = b""
            if not raw:
                if node_id is not None:
                    state[node_id] = "dead"
                    await inform_browser(compute_cluster_status())
                break

            msg = raw.decode("utf-8", errors="replace").rstrip("\n")
            if not msg: continue
            data = json.loads(msg)


            # handle hello
            if node_id is None and data.get("type") == "hello":
                node_id = data["node"]
                nodeFDtable[node_id] = writer

                # an alive node that only reconnected to the relay stays alive
                if state[node_id] == "dead":
                    state[node_id] = "born dead"
                    await inform_browser(compute_cluster_status())

                    # first boot (testy isn't running yet)
                    if node_id not in booted:
                        booted.add(node_id)

                    # tell testy that node is born dead
                    else:
                        try:
                            await relay_to_test_WS.send(json.dumps({"born_dead": node_id}))
                        except websockets.exceptions.ConnectionClosed:
                            pass

            # alive --> node is in the cluster
            if data.get("type") == "alive":
                state[node_id] = "alive"
                await inform_browser(compute_cluster_status())

            # node lost its tcp wire to a peer
            if data.get("type") == "unreachable":
                peer_id = int(data["msg"])
                if state[peer_id] == "alive":
                    # TODO ~ NODE IS SAYING IT CAN'T REACH AN ALIVE NODE!!! NETWORK PARTITION!!!
                    pass

            # forward to browser
            try:
                await relay_to_browser_WS.send(msg)
            except websockets.exceptions.ConnectionClosed:
                pass

    finally:

        # when node dies, its writer is removed from the FD table
        if nodeFDtable.get(node_id) is writer:
            del nodeFDtable[node_id]
        writer.close()

async def on_browser(websocket):
    global relay_to_browser_WS, relay_to_test_WS

    # assign handlers
    if relay_to_browser_WS is None: relay_to_browser_WS = websocket
    else: relay_to_test_WS = websocket

    try:
        async for raw in websocket:
            data = json.loads(raw)

            # start test
            if data["to"] == "relay":
                if data["msg"] == "run_test.py":
                    await asyncio.create_subprocess_exec("python3", "test.py")

            # forward msg to node
            else:
                writer = nodeFDtable[data["to"]]
                writer.write((data["msg"] + "\n").encode())
                await writer.drain()

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        if relay_to_browser_WS is websocket:
            relay_to_browser_WS = None
        if relay_to_test_WS is websocket:
            relay_to_test_WS = None

async def main():

    # accept incoming con req from browser
    async with websockets.serve(on_browser, HOST, WS_PORT):
        while relay_to_browser_WS is None:
            await asyncio.sleep(0.2)

        print("relay & browser are connected", flush=True)

        # accept incoming con req from node
        tcp_server = await asyncio.start_server(on_node, HOST, TCP_PORT)
        async with tcp_server:
            await tcp_server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())


