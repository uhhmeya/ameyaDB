# TODO ~ when test tells node to terminate for 10s, the node sends crash 10s to browser
#  so that browser can display that the node has died. Problem is that if the node
#  dies before the message hits the relay, then node is down but browser thinks its up!
#  Fix this by making the node wait for an ACK to the crash msg before it self deletes

import asyncio
import websockets
import json

HOST = "0.0.0.0" # anyone can connect
WS_PORT = 8765 # browser + testy
TCP_PORT = 9000  # nodes

# handlers
relay_to_browser_WS = None
relay_to_test_WS = None

nodeFDtable = {}
booted = set()

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

                # first boot
                if node_id not in booted:
                    booted.add(node_id)

                # inform test that node is revived
                else:
                    try:
                        await relay_to_test_WS.send(json.dumps({"revived": node_id}))
                    except websockets.exceptions.ConnectionClosed:
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


