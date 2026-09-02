import asyncio
import websockets
import os
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

nodeFDtable = {}

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")

async def run_test():
    proc = await asyncio.create_subprocess_exec("python3", "test.py",)
    returncode = await proc.wait()
    log(f"test.py exited with code {returncode}")

async def send_to_browser(msg):
    if browser is None:
        log(f"FATAL: No browser connected relay dropped msg : {msg}")
        os._exit(1)
    try:
        await browser.send(msg)
    except websockets.exceptions.ConnectionClosed:
        log("FATAL: browser connection closed mid-send")
        os._exit(1)

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

            # who are we talking to?
            if node_id is None:
                node_id = json.loads(msg)["node"]
                nodeFDtable[node_id] = writer
                log(f"node{node_id} is idle and connected to relay")

            await send_to_browser(msg)


    finally:
        if nodeFDtable.get(node_id) is writer:
            del nodeFDtable[node_id]
            log(f"node{node_id} wire broke")
        writer.close()


async def send_to_node(node, text):
    writer = nodeFDtable[node]
    writer.write((text + "\n").encode())
    await writer.drain()
    log(f"node{node} <- {text}")


async def on_WS(websocket):
    global browser
    conn_id = websocket.remote_address[1]

    if browser is None:
        browser = websocket
        log(f"relay & browser are connected")

    try:
        async for raw in websocket:
            data = json.loads(raw)

            # {"to": n, "msg": text} -> forward text to node n
            if "to" in data:
                await send_to_node(data["to"], data["msg"])

            elif data["msg"] == "run_test.py":
                asyncio.create_task(run_test())

    except websockets.exceptions.ConnectionClosed:
        log(f"WS client ({conn_id}) disconnected")

    finally:
        if browser is websocket:
            browser = None

async def main():

    # browser must connect to relay first
    async with websockets.serve(on_WS, WS_HOST, WS_PORT):
        while browser is None:
            await asyncio.sleep(0.2)

        # calls on_TCP() everytime node connects to relay
        tcp_server = await asyncio.start_server(on_TCP, TCP_HOST, TCP_PORT)
        async with tcp_server:
            await tcp_server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())