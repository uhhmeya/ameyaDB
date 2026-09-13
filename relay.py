import asyncio
import websockets
import json
from datetime import datetime

# any computer can connect
TCP_HOST = "0.0.0.0"
WS_HOST = "0.0.0.0"

# nodes send msg to 9000
# relay reads msg from 9000
TCP_PORT = 9000

# relay & browser talk over socket
# socket is built over port 8765
WS_PORT = 8765

# browser is not connected yet
browser = None

# test.py dials in as a second websocket, after the browser
test = None

nodeFDtable = {}

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")

async def run_test():
    proc = await asyncio.create_subprocess_exec("python3", "test.py")
    returncode = await proc.wait()
    log(f"test.py exited with code {returncode}")

async def send_to_browser(msg):
    if browser is None:
        return
    try:
        await browser.send(msg)
    except websockets.exceptions.ConnectionClosed:
        pass

async def tell_test(msg):
    if test is None:
        return
    try:
        await test.send(json.dumps(msg))
    except websockets.exceptions.ConnectionClosed:
        pass

async def on_TCP(reader, writer):
    node_id = None
    try:

        # extract line from TCP
        while True:
            raw = await reader.readline()
            if not raw:
                break
            msg = raw.decode("utf-8", errors="replace").rstrip("\n")
            if not msg:
                continue

            data = json.loads(msg)

            # who are we talking to? a node reaches us before it is allowed to
            # do anything, so first contact means it is sitting there born dead
            if node_id is None:
                node_id = data["node"]
                nodeFDtable[node_id] = writer
                log(f"node{node_id} born dead")
                await tell_test({"born_dead": node_id})

            # it says this once a connect message has flipped its alive flag
            if data.get("type") == "awake":
                log(f"node{node_id} up")

            await send_to_browser(msg)

    finally:
        if nodeFDtable.get(node_id) is writer:
            del nodeFDtable[node_id]
            log(f"node{node_id} wire broke")
        writer.close()

async def send_to_node(node, text):
    writer = nodeFDtable.get(node)
    if writer is None:
        log(f"node{node} not connected -- dropped: {text}")
        return False
    try:
        writer.write((text + "\n").encode())
        await writer.drain()
    except (ConnectionError, OSError):
        log(f"node{node} wire broke mid-send -- dropped: {text}")
        return False
    log(f"node{node} <- {text}")
    return True

async def on_WS(websocket):
    global browser, test

    if browser is None:
        browser = websocket
        log("relay & browser are connected")
    else:
        test = websocket   # the browser is always first in, so this one is test.py

    try:
        async for raw in websocket:
            data = json.loads(raw)

            # {"to": n, "msg": text} -> forward text to node n
            if "to" in data:
                await send_to_node(data["to"], data["msg"])

            elif data["msg"] == "run_test.py":
                asyncio.create_task(run_test())

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        if browser is websocket:
            browser = None
            log("browser detached -- telemetry dropped until it returns")
        if test is websocket:
            test = None

# connect to browser
# call on_TCP when node connects
async def main():

    # connect to browser
    async with websockets.serve(on_WS, WS_HOST, WS_PORT):
        while browser is None:
            await asyncio.sleep(0.2)

        # accept node connections
        tcp_server = await asyncio.start_server(on_TCP, TCP_HOST, TCP_PORT)
        async with tcp_server:
            await tcp_server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())