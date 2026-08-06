import asyncio
import websockets

# only ports from this computer can connect
TCP_HOST = "127.0.0.1"
WS_HOST = "127.0.0.1"

# nodes send msg to 9000
# relay reads msg from 9000
TCP_PORT = 9000

# relay & browser talk over socket
# socket is built over port 8765
WS_PORT = 8765

# browser is not connected yet
browser = None


async def send_to_browser(msg):
    if browser is None:
        print(f"FATAL: No browser connected relay dropped msg : {msg}")
        os._exit(1)
    try:
        await browser.send(msg)
    except websockets.exceptions.ConnectionClosed:
        print("FATAL: browser connection closed mid-send")
        os._exit(1)

# reader receives bytes from wire
# writer sends bytes into wire
async def on_TCP(reader, writer):
    peer = writer.get_extra_info("peername")
    print(f"TCP node connected: {peer}")
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

            await send_to_browser(msg)

    finally:
        print(f"TCP node disconnected: {peer}")
        writer.close()


# called when browser connects to relay
async def on_WS(websocket):
    global browser
    browser = websocket
    print(f"browser connected: {websocket.remote_address}")

    # keep browser connected
    try:
        await websocket.wait_closed()

    # if relay crashes or browser closes...
    finally:
        if browser is websocket:
            browser = None
        print(f"browser disconnected: {websocket.remote_address}")

async def main():

    # calls on_TCP() everytime node connects to relay
    tcp_server = await asyncio.start_server(on_TCP, TCP_HOST, TCP_PORT)

    # calls on_WS when browser connects to relay
    async with websockets.serve(on_WS, WS_HOST, WS_PORT):
        async with tcp_server:
            await tcp_server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())




