import asyncio
import websockets
import json
import time

HOST = "0.0.0.0" # anyone can connect
WS_PORT = 8765 # browser + testy
TCP_PORT = 9000  # nodes
EC2_PORT = 9001
NUM_NODES = 5

# handlers
relay_to_browser_WS = None
relay_to_test_WS = None

nodeFDtable = {}
nodes_seen_before = set()
state = {n: "dead" for n in range(NUM_NODES)}
compile_failed = False

def compute_health():
    alive = [n for n in state if state[n] == "alive"]
    born_dead = [n for n in state if state[n] == "born dead"]
    dead = [n for n in state if state[n] == "dead"]
    return f"alive {alive} born dead {born_dead} dead {dead}"

async def inform_browser():
    try:
        await relay_to_browser_WS.send(json.dumps({
            "type": "cluster",
            "msg": compute_health(),
            "born_dead_or_alive": len([n for n in state if state[n] != "dead"]),
            "compile_failed": compile_failed,
            "wall_us": time.time_ns() // 1000,
        }))
    except websockets.exceptions.ConnectionClosed:
        pass

async def on_node_process(reader, writer):
    node_id = None
    try:
        while True:

            # parse msg 1
            try: very_raw_msg = await reader.readline()
            except ConnectionResetError: very_raw_msg = b""

            # handle FIN
            if not very_raw_msg:
                if node_id is not None:
                    state[node_id] = "dead"
                    await inform_browser()
                break

            # parse msg 2
            raw_msg = very_raw_msg.decode("utf-8", errors="replace").rstrip("\n")
            if not raw_msg: continue
            msg = json.loads(raw_msg)


            # handle hi
            if node_id is None and msg.get("type") == "hello":
                node_id = msg["node"]
                nodeFDtable[node_id] = writer

                # dead --> born dead
                if state[node_id] == "dead":
                    state[node_id] = "born dead"
                    await inform_browser()

                    is_restart = node_id in nodes_seen_before
                    nodes_seen_before.add(node_id)

                    # tell testy that node is born dead
                    if is_restart:
                        try: await relay_to_test_WS.send(json.dumps({"born_dead": node_id}))
                        except websockets.exceptions.ConnectionClosed: pass

            # alive --> node is in the cluster
            if msg.get("type") == "alive":
                state[node_id] = "alive"
                await inform_browser()

            # node lost its tcp wire to a peer
            if msg.get("type") == "unreachable":
                peer_id = int(msg["msg"])
                if state[peer_id] == "alive":
                    # TODO ~ NODE IS SAYING IT CAN'T REACH AN ALIVE NODE!!! NETWORK PARTITION!!!
                    pass

    finally:
        if nodeFDtable.get(node_id) is writer:
            del nodeFDtable[node_id]
        writer.close()

# tell browser if compile failed
async def on_ec2(reader, writer):
    global compile_failed
    try:
        raw_msg = await reader.readline()
        if raw_msg and json.loads(raw_msg).get("type") == "compile":
            compile_failed = True
            await inform_browser()
    finally:
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
        tcp_server = await asyncio.start_server(on_node_process, HOST, TCP_PORT)
        ec2_server = await asyncio.start_server(on_ec2, HOST, EC2_PORT)
        async with tcp_server, ec2_server:
            await tcp_server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())


