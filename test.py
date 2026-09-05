import asyncio
import json
import time
from datetime import datetime

import websockets

import client as clientlib

TEST_TO_RELAY_WS = "ws://127.0.0.1:8765"

NUM_NODES     = 5
NUM_CLIENTS   = 10
DOWNTIME_SECS = 15     # how long a terminated node stays down
REJOIN_GRACE  = 8      # crash.sh needs a beat past its sleep to restart + redial
SETTLE_SECS   = 20     # let the cluster re-elect and clients re-find the leader
TICK_SECS     = 2

ws   = None
pool = None


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)

async def send(node, text):
    await ws.send(json.dumps({"to": node, "msg": text}))


async def connect_all():
    for n in range(NUM_NODES):
        await send(n, "connect all")


async def stats_ticker():
    prev, last = 0, time.monotonic()
    try:
        while True:
            await asyncio.sleep(TICK_SECS)
            snap = pool.stats.snapshot()
            now  = time.monotonic()

            delta = snap["committed"] - prev
            rate  = delta / (now - last)
            prev, last = snap["committed"], now

            leaders = ", ".join(f"n{k}={v}" for k, v in sorted(snap["by_leader"].items())) or "-"
            log(f"[stats] +{delta:<5d} ({rate:6.1f}/s)  total={snap['committed']:<7d} "
                f"redirect={snap['redirects']:<6d} connerr={snap['conn_errs']:<5d} "
                f"failed={snap['failed']:<5d} [{leaders}]")
    except asyncio.CancelledError:
        pass


async def scenario():
    log("[chaos] waking cluster")
    await connect_all()
    await asyncio.sleep(10)

    log(f"[chaos] starting {NUM_CLIENTS} clients, writes flow from here on")
    pool.start()
    await asyncio.sleep(10)          # baseline before anything breaks

    for n in range(NUM_NODES):
        log(f"[chaos] ---- terminating node {n} for {DOWNTIME_SECS}s ----")
        await send(n, f"terminate {DOWNTIME_SECS}")

        # Bare "terminate" would default to 30s inside handle_relay_msg
        # (msg.size() > 10 is false for the 9-char word), so always pass it.
        await asyncio.sleep(DOWNTIME_SECS + REJOIN_GRACE)

        log(f"[chaos] node {n} should be back -- re-arming whole cluster")
        await connect_all()
        await asyncio.sleep(SETTLE_SECS)

    log("[chaos] all nodes cycled, draining")
    await asyncio.sleep(10)


async def main():
    global ws, pool
    pool = clientlib.ClientPool(num_clients=NUM_CLIENTS)

    async with websockets.connect(TEST_TO_RELAY_WS) as conn:
        ws = conn
        ticker = asyncio.create_task(stats_ticker())
        try:
            await scenario()
        finally:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
            pool.shutdown()

    f = pool.stats.snapshot()
    log("=" * 72)
    log(f"[final] committed={f['committed']}  failed={f['failed']}  "
        f"redirects={f['redirects']}  conn_errs={f['conn_errs']}")
    log(f"[final] commits by node: {f['by_leader'] or '{}'}")
    log("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())