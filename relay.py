import asyncio
import websockets
import json
from datetime import datetime

# anyone can connect
TCP_HOST = "0.0.0.0"
WS_HOST = "0.0.0.0"

# nodes r/wr over random port
# relay r/wr over port 9000
TCP_PORT = 9000

# browser r/wr over random port
# relay r/wr over port 8765
WS_PORT = 8765

# handlers
relay_to_browser_WS = None
relay_to_test_WS = None

nodeFDtable = {}

async def send_to_browser(msg):
    if relay_to_browser_WS is None:
        return
    try:
        await relay_to_browser_WS.send(msg)
    except websockets.exceptions.ConnectionClosed:
        pass

async def tell_test(msg):
    if relay_to_test_WS is None:
        return
    try:
        await relay_to_test_WS.send(json.dumps(msg))
    except websockets.exceptions.ConnectionClosed:
        pass

async def on_node(reader, writer):
    node_id = None
    try:

        # get msg from node
        while True:
            raw = await reader.readline()
            if not raw:
                break
            msg = raw.decode("utf-8", errors="replace").rstrip("\n")
            if not msg:
                continue
            data = json.loads(msg)


            # handle hello
            if node_id is None and data.get("type") == "hello":
                node_id = data["node"]
                nodeFDtable[node_id] = writer
                await tell_test({"born_dead": node_id})

            # forward
            await send_to_browser(msg)

    finally:
        if nodeFDtable.get(node_id) is writer:
            del nodeFDtable[node_id]
        writer.close()

async def send_to_node(node, text):
    writer = nodeFDtable.get(node)
    if writer is None:
        return False
    try:
        writer.write((text + "\n").encode())
        await writer.drain()
    except (ConnectionError, OSError):
        return False
    return True

async def on_browser(websocket):
    global relay_to_browser_WS, relay_to_test_WS

    if relay_to_browser_WS is None:
        relay_to_browser_WS = websocket
    else:
        relay_to_test_WS = websocket

    try:
        async for raw in websocket:
            data = json.loads(raw)

            # start test
            if data["to"] == "relay":
                if data["msg"] == "run_test.py":
                    await asyncio.create_subprocess_exec("python3", "test.py")

            # forward msg to node
            else:
                await send_to_node(data["to"], data["msg"])
                # TODO ~ see if you can inline this method

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        if relay_to_browser_WS is websocket:
            relay_to_browser_WS = None
        if relay_to_test_WS is websocket:
            relay_to_test_WS = None


async def main():

    # accept incoming con req from browser
    async with websockets.serve(on_browser, WS_HOST, WS_PORT):
        while relay_to_browser_WS is None:
            await asyncio.sleep(0.2)

        print("relay & browser are connected", flush=True)

        # accept incoming con req from node
        tcp_server = await asyncio.start_server(on_node, TCP_HOST, TCP_PORT)
        async with tcp_server:
            await tcp_server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())