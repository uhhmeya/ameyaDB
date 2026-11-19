import asyncio
import websockets
import json
import time

HOST = "0.0.0.0" # anyone can connect
WS_PORT = 8765 # browser + testy
NODE_PORT = 9000 # node processes
EC2_PORT = 9001 # an ec2's build script, only when compiling fails
NUM_NODES = 5

# handlers
browser_ws = None
testy_ws = None

node_writers = {}
nodes_seen_before = set()
state = {n: "dead" for n in range(NUM_NODES)}
compile_failed = False

async def send(ws, payload):
    if ws is None: return
    try: await ws.send(json.dumps(payload))
    except websockets.exceptions.ConnectionClosed: pass

async def inform_browser(event):
    await send(browser_ws, {
        "event": event,
        "born_dead_or_participating": len([n for n in state if state[n] != "dead"]),
        "compile_failed": compile_failed,
        "wall_us": time.time_ns() // 1000,
    })

async def set_state(node_id, new_state):
    state[node_id] = new_state
    if len(set(state.values())) == 1:
        await inform_browser(f"all nodes {new_state}")
    else:
        await inform_browser(f"{node_id} {new_state}")

async def on_node_process(reader, writer):
    node_id = None
    try:
        while True:
            try: line = await reader.readline()
            except ConnectionResetError: line = b""

            # FIN or RST
            if not line:
                await set_state(node_id, "dead")
                break

            msg = json.loads(line)

            if msg["type"] == "hello":
                node_id = msg["node"]
                node_writers[node_id] = writer
                await set_state(node_id, "born dead")

                is_restart = node_id in nodes_seen_before
                nodes_seen_before.add(node_id)

                # tell testy that node is born dead
                if is_restart:
                    await send(testy_ws, {"born_dead": node_id})

            elif msg["type"] == "participating":
                await set_state(node_id, "participating")

            elif msg["type"] == "unreachable":
                peer_id = int(msg["msg"])
                if state[peer_id] == "participating":
                    # TODO : NETWORK PARTITION!!!
                    pass

    finally:
        del node_writers[node_id]
        writer.close()

# tell browser if compile failed
async def on_ec2(reader, writer):
    global compile_failed
    msg = json.loads(await reader.readline())
    compile_failed = True
    await inform_browser(f"{msg['node']} failed to compile")
    writer.close()

async def on_browser_or_testy(websocket):
    global browser_ws, testy_ws

    # the browser connects first, testy second
    if browser_ws is None: browser_ws = websocket
    else: testy_ws = websocket

    try:
        async for raw in websocket:
            data = json.loads(raw)

            # start test
            if data["to"] == "relay":
                await asyncio.create_subprocess_exec("python3", "test.py")

            # forward msg to node
            else:
                writer = node_writers[data["to"]]
                writer.write((data["msg"] + "\n").encode())
                await writer.drain()

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        if browser_ws is websocket: browser_ws = None
        if testy_ws is websocket: testy_ws = None

async def main():

    # accept incoming con req from browser
    async with websockets.serve(on_browser_or_testy, HOST, WS_PORT):
        while browser_ws is None:
            await asyncio.sleep(0.2)

        print("relay & browser are connected", flush=True)

        # accept incoming con req from node processes and ec2 build scripts
        node_server = await asyncio.start_server(on_node_process, HOST, NODE_PORT)
        ec2_server = await asyncio.start_server(on_ec2, HOST, EC2_PORT)
        async with node_server, ec2_server:
            await node_server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
