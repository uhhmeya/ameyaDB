import asyncio
import websockets
import glob
import json
import subprocess
import time

HOST = "0.0.0.0"
WS_PORT = 8765
NODE_PORT = 9000
EC2_PORT = 9001
NUM_NODES = 5

EPOCH_PATH = "relay_epoch"
RUNS_PATH = "runs"

browsers = set()
testy_ws = None
testy_process = None

node_writers = {}
nodes_seen_before = set()
state = {n: "dead" for n in range(NUM_NODES)}
compile_failed = False

epoch = 0
keep_old_data = False

catalog = {}
history = []
current_run = []
current_sweep = None

async def send(ws, payload):
    if ws is None: return
    try: await ws.send(json.dumps(payload))
    except websockets.exceptions.ConnectionClosed: pass

async def send_to_node(node_id, text):
    writer = node_writers.get(node_id)
    if writer is None: return
    try:
        writer.write((text + "\n").encode())
        await writer.drain()
    except ConnectionError: pass

def cluster_status(event=None):
    return {
        "event": event,
        "born_dead_or_participating": len([n for n in state if state[n] != "dead"]),
        "compile_failed": compile_failed,
        "busy": testy_ws is not None,
        "wall_us": time.time_ns() // 1000,
    }

async def inform_browser(event=None, report=None):
    payload = cluster_status(event)
    payload.update(report or {})
    for browser_ws in list(browsers):
        await send(browser_ws, payload)

def load_epoch():
    global epoch, keep_old_data
    try:
        with open(EPOCH_PATH) as f: saved = f.read().split()
        epoch, keep_old_data = int(saved[0]), saved[1] == "1"
    except (OSError, ValueError, IndexError):
        start_new_epoch(False)

def start_new_epoch(keep):
    global epoch, keep_old_data
    epoch, keep_old_data = time.time_ns() // 1000000, keep
    with open(EPOCH_PATH, "w") as f: f.write(f"{epoch} {int(keep)}")

async def reset_cluster(keep):
    start_new_epoch(keep)
    for node_id in list(node_writers):
        await send_to_node(node_id, f"epoch {epoch} {int(keep_old_data)}")
    await inform_browser("database cleared" + (", old data kept on the nodes for debugging" if keep else ""))

async def heal_cluster():
    for node_id in list(node_writers):
        await send_to_node(node_id, "link all 0 0 0")
        await send_to_node(node_id, "disk 0")
        await send_to_node(node_id, "connect all")

async def on_node_process(reader, writer):
    node_id = None
    try:
        while True:
            try: line = await reader.readline()
            except ConnectionResetError: line = b""

            if not line:
                if node_id is not None and node_writers.get(node_id) is writer:
                    state[node_id] = "dead"
                    await inform_browser(f"node{node_id} down")
                    await send(testy_ws, {"down": node_id})
                break

            msg = json.loads(line)

            if msg["type"] == "hello":
                node_id = msg["node"]
                node_writers[node_id] = writer
                state[node_id] = "born dead"

                await send_to_node(node_id, f"epoch {epoch} {int(keep_old_data)}")

                is_restart = node_id in nodes_seen_before
                nodes_seen_before.add(node_id)

                if is_restart:
                    await inform_browser(f"node{node_id} up")
                else:
                    await inform_browser()
                await send(testy_ws, {"born_dead": node_id})

            elif msg["type"] == "participating":
                state[node_id] = "participating"

            elif msg["type"] == "done":
                await send(testy_ws, {"done": node_id})

            elif msg["type"] == "agreement_check_res":
                await send(testy_ws, {"node": node_id, "agreement_check_res": msg["msg"]})

            elif msg["type"] == "unreachable":
                pass

            else:
                await send(testy_ws, {"tm": msg})

    finally:
        if node_id is not None and node_writers.get(node_id) is writer:
            del node_writers[node_id]
        writer.close()

async def on_ec2(reader, writer):
    global compile_failed
    msg = json.loads(await reader.readline())

    if msg["type"] == "cut":
        await send(testy_ws, {"tm": {"node": msg["node"], "type": "cut", "wall_us": msg["wall_us"], "msg": ""}})

    else:
        compile_failed = True
        await inform_browser(f"node{msg['node']} failed to compile")
    writer.close()

async def start_test(config):
    global testy_process
    if testy_ws is not None or (testy_process and testy_process.returncode is None):
        await inform_browser("a test is already running")
        return
    testy_process = await asyncio.create_subprocess_exec("python3", "test.py", json.dumps(config))

async def on_testy_report(report):
    global current_run, current_sweep
    del report["to"]

    if "run" in report:
        current_run = []
        if not report["run"]["sweep"]: current_sweep = None

    if "sweep" in report: current_sweep = report
    elif len(current_run) < 5000: current_run.append(report)
    if "summary" in report: history.append(report["summary"]["short"])

    await inform_browser(report=report)

async def catch_up(browser_ws):
    await send(browser_ws, {**cluster_status(), "catalog": catalog, "history": history})
    if current_sweep: await send(browser_ws, {**cluster_status(), **current_sweep})
    for report in list(current_run):
        await send(browser_ws, {**cluster_status(), **report})

async def on_browser_or_testy(websocket):
    global testy_ws

    browsers.add(websocket)
    await inform_browser()

    try:
        async for raw in websocket:
            data = json.loads(raw)

            if data["to"] == "relay" and data["msg"] == "i am testy":
                browsers.discard(websocket)
                testy_ws = websocket
                await send(testy_ws, {"cluster": state})
                await inform_browser()

            elif data["to"] == "relay" and data["msg"] == "i am browser":
                await catch_up(websocket)

            elif data["to"] == "relay" and data["msg"] == "reset":
                await reset_cluster(data["keep"])

            elif data["to"] == "relay" and data["msg"] == "stop":
                if testy_process and testy_process.returncode is None: testy_process.terminate()

            elif data["to"] == "relay":
                await start_test(data.get("config", {}))

            elif data["to"] == "browser":
                await on_testy_report(data)

            else:
                await send_to_node(data["to"], data["msg"])

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        browsers.discard(websocket)
        if testy_ws is websocket:
            testy_ws = None
            await heal_cluster()
            await inform_browser()

def load_catalog_and_history():
    global catalog

    try: catalog = json.loads(subprocess.check_output(["python3", "test.py", "catalog"]))
    except (OSError, ValueError, subprocess.CalledProcessError): catalog = {}

    for path in sorted(glob.glob(f"{RUNS_PATH}/*/summary.json")):
        try:
            with open(path) as f: history.append(json.load(f)["summary"]["short"])
        except (OSError, ValueError, KeyError): pass

async def main():
    load_epoch()
    load_catalog_and_history()

    async with websockets.serve(on_browser_or_testy, HOST, WS_PORT, max_size=None):
        while not browsers:
            await asyncio.sleep(0.2)

        print("relay & browser are connected", flush=True)

        node_server = await asyncio.start_server(on_node_process, HOST, NODE_PORT)
        ec2_server = await asyncio.start_server(on_ec2, HOST, EC2_PORT)
        async with node_server, ec2_server:
            await node_server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
