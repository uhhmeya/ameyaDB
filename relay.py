import asyncio
import websockets
import os
import json
from datetime import datetime
import re

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

nodes = {}

fd_parser = re.compile(r"\(node (\d+)\)")

SLEEP_THRESHOLD = 60 # seconds

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}")


async def run_test():
    proc = await asyncio.create_subprocess_exec("python3", "test.py",)
    returncode = await proc.wait()
    log(f"test.py exited with code {returncode}")

async def send_to_browser(msg):
    if browser is None:
        print(f"FATAL: No browser connected relay dropped msg : {msg}")
        os._exit(1)
    try:
        await browser.send(msg)
    except websockets.exceptions.ConnectionClosed:
        print("FATAL: browser connection closed mid-send")
        os._exit(1)

def parseFD(msg, writer):
    m = fd_parser.search(msg)
    if not m:
        return None
    node_id = int(m.group(1))
    nodes[node_id] = writer
    log(f"node{node_id} is idle and connected to relay")
    return node_id

# reader receives bytes from wire
# writer sends bytes into wire
async def on_TCP(reader, writer):

    node_id = None
    try:

        # extract line from TCP
        while True:
            raw = await reader.readline()
            if not raw:
                break

            # str(msg)
            msg = raw.decode("utf-8", errors="replace").rstrip("\n")
            if not msg:
                continue

            # who are we talking to?
            if node_id is None:
                node_id = parseFD(msg, writer)

            await send_to_browser(msg)

    # when tcp wire breaks
    finally:
        if node_id is not None:
            del nodes[node_id]
            log(f"node{node_id} unreachable")
        writer.close()

# called when browser connects to relay
async def on_WS(websocket):
    global browser
    browser = websocket
    conn_id = websocket.remote_address[1]
    log(f"relay & browser are connected")

    try:
        async for raw in websocket:
            msg = json.loads(raw)["msg"]
            if msg == "run_test.py":
                asyncio.create_task(run_test())

    except websockets.exceptions.ConnectionClosed:
        log(f"browser ({conn_id}) disconnected")

    return

async def main():

    # calls on_TCP() everytime node connects to relay
    tcp_server = await asyncio.start_server(on_TCP, TCP_HOST, TCP_PORT)

    # calls on_WS when browser connects to relay
    async with websockets.serve(on_WS, WS_HOST, WS_PORT):
        async with tcp_server:
            await tcp_server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())