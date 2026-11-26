import asyncio
import bisect
import json
import os
import random
import secrets
import struct
import sys
import time
import websockets

import chaos
import checks

RELAY_WS_URL = "ws://127.0.0.1:8765"

NUM_NODES = 5

CLIENT_PORT = 7000
OP_WR = 1
OP_RD = 2
I_AM_LEADER = 11
I_AM_NOT_LEADER = 12
IDK = 13

WARMUP_SEC = 5
HEALTHY_SEC = 4
SETTLE_SEC = 2
RECOVER_MAX_SEC = 30
CLIENT_TIMEOUT_SEC = 1.0
SCOUT_EVERY_SEC = 0.025
SCOUT_TIMEOUT_SEC = 0.3
FRAME_EVERY_SEC = 0.5

config = {
    "mode": "chaos",
    "name": "",
    "seed": None,
    "seconds": 60,
    "flags": {},
    "label": "",
    "fresh": True,
    "hard": True,
    "clients": 10,
    "think_ms": 5,
    "keys": 200,
    "gap": 3.0,
    "repeats": 1,
    "xs": None,
}

relay_ws = None
cluster = {}
cluster_known = None
born_dead_flags = []
done_flags = []
db_state_flags = []
db_states = {}
deaf_to = set()
is_test_over = False
phase = "idle"
frames = []
viable_log = []
worst_lag_ms = 0
vreqs_seen = {}

async def send_to_node(node_id, text):
    await relay_ws.send(json.dumps({"to": node_id, "msg": text}))

async def send_to_browser(report):
    await relay_ws.send(json.dumps(dict(report, to="browser")))

async def listen_to_relay():
    async for raw in relay_ws:
        msg = json.loads(raw)

        if "born_dead" in msg:
            node_id = msg["born_dead"]
            cluster[node_id] = "born dead"
            checks.up[node_id] = False
            deaf_to.discard(node_id)
            born_dead_flags[node_id].set()
            if phase != "idle": await chaos.wake(node_id)

        elif "down" in msg:
            cluster[msg["down"]] = "dead"
            checks.on_node_down(msg["down"])

        elif "tm" in msg:
            node_id = msg["tm"]["node"]
            if node_id in deaf_to: continue
            if msg["tm"]["type"] in ("stat", "booted"): cluster[node_id] = "participating"
            checks.on_node_msg(msg["tm"])

        elif "done" in msg:
            done_flags[msg["done"]].set()

        elif "agreement_check_res" in msg:
            db_states[msg["node"]] = msg["agreement_check_res"]
            db_state_flags[msg["node"]].set()

        elif "cluster" in msg:
            for node_id, state in msg["cluster"].items():
                cluster[int(node_id)] = state
            cluster_known.set()

async def wait_for_all(flags, timeout):
    try: await asyncio.wait_for(asyncio.gather(*[flag.wait() for flag in flags]), timeout)
    except asyncio.TimeoutError: pass

async def wait_until(is_true, timeout):
    give_up = time.time() + timeout
    while time.time() < give_up:
        if is_true(): return True
        await asyncio.sleep(0.05)
    return False


def encode_write(key, val):
    key, val = key.encode(), val.encode()
    return bytes([OP_WR]) + struct.pack("<I", len(key)) + key + struct.pack("<I", len(val)) + val

def encode_read(key):
    key = key.encode()
    return bytes([OP_RD]) + struct.pack("<I", len(key)) + key

def guess(node_id):
    return f"node-{node_id}.ameyadb.internal"

async def run_client(client_num, rng, keys, think_sec):

    guess_node = rng.randrange(NUM_NODES)
    wr_num = 0

    while not is_test_over:
        writer = None

        try:
            conn = asyncio.open_connection(guess(guess_node), CLIENT_PORT)
            reader, writer = await asyncio.wait_for(conn, timeout=1)

            while not is_test_over:

                wr_num += 1
                key = f"c{client_num}k{rng.randrange(keys)}"
                began = time.time()
                writer.write(encode_write(key, str(wr_num)))

                try:
                    reply = await asyncio.wait_for(reader.readexactly(5), timeout=CLIENT_TIMEOUT_SEC)
                except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                    checks.wrote(key, wr_num, "timeout", began, time.time())
                    guess_node = rng.randrange(NUM_NODES)
                    break

                leader_status = reply[0]

                if leader_status == I_AM_LEADER:
                    checks.wrote(key, wr_num, "ok", began, time.time())
                    await asyncio.sleep(think_sec)

                elif leader_status == I_AM_NOT_LEADER:
                    checks.wrote(key, wr_num, "redirect", began, time.time())
                    leader_id = struct.unpack_from("<i", reply, 1)[0]
                    guess_node = leader_id if 0 <= leader_id < NUM_NODES else rng.randrange(NUM_NODES)
                    break

                else:
                    checks.wrote(key, wr_num, "idk", began, time.time())
                    guess_node = rng.randrange(NUM_NODES)
                    break

        except (OSError, asyncio.TimeoutError):
            guess_node = rng.randrange(NUM_NODES)

        finally:

            if writer:
                writer.close()
            await asyncio.sleep(0.02)

async def run_scout(node_id):

    wr_num = 0

    while not is_test_over:
        writer = None

        try:
            conn = asyncio.open_connection(guess(node_id), CLIENT_PORT)
            reader, writer = await asyncio.wait_for(conn, timeout=0.5)

            while not is_test_over:

                wr_num += 1
                key = f"s{node_id}k{wr_num % 20}"
                writer.write(encode_write(key, str(wr_num)))

                try:
                    reply = await asyncio.wait_for(reader.readexactly(5), timeout=SCOUT_TIMEOUT_SEC)
                except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                    checks.probed(key, wr_num, "timeout", time.time())
                    break

                if reply[0] == I_AM_LEADER: checks.probed(key, wr_num, "ok", time.time())
                elif reply[0] == IDK: checks.probed(key, wr_num, "idk", time.time())
                await asyncio.sleep(SCOUT_EVERY_SEC)

        except (OSError, asyncio.TimeoutError):
            pass

        finally:

            if writer:
                writer.close()
            await asyncio.sleep(SCOUT_EVERY_SEC)

def make_frame():
    counts = checks.next_tick()
    lat = sorted(counts["lat"])

    nodes, vreq = [], 0
    for node_id in range(NUM_NODES):
        stat = checks.stats.get(node_id)
        if not checks.up[node_id] or stat is None:
            nodes.append({"up": 0})
            continue

        nodes.append({"up": 1 if checks.heard_from(node_id, 0.8) else 2, "role": stat["role"],
                      "term": stat["term"], "commit": stat["commit"], "conn": stat["conn"]})

        seen = vreqs_seen.get(node_id, 0)
        vreq += stat["vreq"] - seen if stat["vreq"] >= seen else stat["vreq"]
        vreqs_seen[node_id] = stat["vreq"]

    return {
        "t": round(checks.now(), 2), "phase": phase, "nodes": nodes,
        "ok": counts["ok"], "redirect": counts["redirect"], "idk": counts["idk"], "timeout": counts["timeout"],
        "p50": checks.pct(lat, 0.5), "p99": checks.pct(lat, 0.99), "max": lat[-1] if lat else None,
        "served": counts["served"], "viable": chaos.viable_now(), "links": chaos.link_codes(), "vreq": vreq,
        "ev": checks.take_new_events(), "fx": [dict(fault) for fault in chaos.take_changed()],
    }

async def send_frames_4ever():
    while True:
        await asyncio.sleep(FRAME_EVERY_SEC)
        frame = make_frame()
        frames.append(frame)
        await send_to_browser({"frame": frame})

async def watch_viable_4ever():
    while True:
        answer = chaos.viable_now()
        if not viable_log or viable_log[-1][1] != answer:
            viable_log.append((checks.now(), answer))
        await asyncio.sleep(0.1)

async def watch_myself_4ever():
    global worst_lag_ms
    while True:
        before = time.perf_counter()
        await asyncio.sleep(0.01)
        worst_lag_ms = max(worst_lag_ms, (time.perf_counter() - before - 0.01) * 1000)

def viable_spans(end):
    spans = []
    for i, (t, answer) in enumerate(viable_log):
        if answer: spans.append((t, viable_log[i + 1][0] if i + 1 < len(viable_log) else end))
    return spans


async def reset_cluster(keep):
    restarting = [node_id for node_id in range(NUM_NODES) if cluster.get(node_id) == "participating"]
    for node_id in restarting:
        born_dead_flags[node_id].clear()
    deaf_to.update(restarting)

    await relay_ws.send(json.dumps({"to": "relay", "msg": "reset", "keep": keep}))
    await wait_for_all([born_dead_flags[node_id] for node_id in restarting], 30)
    deaf_to.clear()

async def break_things(rng, run):
    if run["mode"] == "chaos":
        await chaos.random_chaos(rng, run["seconds"], run["gap"])

    elif run["mode"] == "scenario":
        await chaos.SCENARIOS[run["name"]][0](rng, run["seconds"])

    else:
        fault = chaos.SWEEPS[run["name"]][0]
        if fault: await fault(rng, run["seconds"], run["x"])
        else: await chaos.SCENARIOS[run["x"]][0](rng, chaos.SCENARIOS[run["x"]][2])

async def wait_for_service(healed_at):
    while checks.now() < healed_at + RECOVER_MAX_SEC:
        await asyncio.sleep(0.1)
        now = checks.now()
        first = bisect.bisect_left(checks.acks, healed_at)
        gaps = checks.find_outage(checks.acks[first:], healed_at, now, checks.OUTAGE_MIN_SEC)
        back_at = gaps[-1][1] if gaps else healed_at
        if len(checks.acks) > first and now - back_at >= 1.0:
            return round(back_at - healed_at, 3)
    return None

async def ask_every_node_what_it_holds():
    for flag in db_state_flags:
        flag.clear()
    db_states.clear()

    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "agreement_check_req")
    await wait_for_all(db_state_flags, 10)

    nodes = []
    for node_id in range(NUM_NODES):
        if node_id in db_states:
            applied, term, keys, digest, apply_hash, log_idx = db_states[node_id].split()
            nodes.append({"applied": int(applied), "term": int(term), "keys": int(keys),
                          "digest": digest, "hash": apply_hash, "log_idx": int(log_idx)})
        else:
            nodes.append(None)
    return nodes

async def check_agreement():
    for flag in done_flags:
        flag.clear()
    for node_id in range(NUM_NODES):
        await send_to_node(node_id, "writes_stopped")
    await wait_for_all(done_flags, 30)

    for attempt in range(15):
        nodes = await ask_every_node_what_it_holds()
        if checks.judge(nodes, []) != "LAGGING": break
        await asyncio.sleep(1)
    return nodes

async def read_back(node_id):
    keys = sorted(set(checks.acked) | set(checks.maybe))
    db = {}
    try:
        conn = asyncio.open_connection(guess(node_id), CLIENT_PORT)
        reader, writer = await asyncio.wait_for(conn, timeout=2)

        for first in range(0, len(keys), 500):
            batch = keys[first:first + 500]
            writer.write(b"".join(encode_read(key) for key in batch))
            for key in batch:
                val_len = struct.unpack("<I", await asyncio.wait_for(reader.readexactly(4), timeout=5))[0]
                val = (await asyncio.wait_for(reader.readexactly(val_len), timeout=5)).decode()
                db[key] = None if val == "KEY_NOT_FOUND" else val
        writer.close()
        return db

    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
        return None

def check(name, ok, detail):
    return {"name": name, "ok": ok, "detail": detail}

def judge_run(run, nodes, db, faults_began, healed_at, measured_until, recover_sec):

    two_leaders = checks.terms_with_two_leaders(checks.wins)
    two_votes = checks.double_votes(checks.votes)
    went_back = checks.term_went_back(checks.terms)
    conflicts = checks.hash_conflicts(checks.marks)
    verdict = checks.judge(nodes, conflicts)
    restarts = len([event for event in checks.events if event[2] == "up"])
    last_term = max([term for node_id, term in checks.terms], default=0)
    from_nowhere = checks.terms_from_nowhere(checks.first_term(), last_term, len(checks.elections), restarts)

    lost, phantoms = [], []
    for key in sorted(db or {}):
        fate = checks.judge_key(db[key], checks.acked.get(key, []), checks.maybe.get(key, set()))
        if fate == "lost": lost.append(key)
        if fate == "phantom": phantoms.append(key)

    results = [
        check("one leader per term", not two_leaders,
              f"terms {two_leaders[:5]} had two leaders" if two_leaders else f"{len(set(checks.wins))} leaders, each alone in its term"),
        check("one vote per term", not two_votes,
              f"(node, term) {two_votes[:5]} voted for two candidates" if two_votes else f"{len(checks.votes)} votes looked at"),
        check("terms never go back", went_back is None,
              "node%d went from term %d to %d" % went_back if went_back else "every node's term only went up"),
        check("terms only grow through elections", from_nowhere == 0,
              f"term reached {last_term} but {from_nowhere} of those steps had no election behind them" if from_nowhere
              else f"term {checks.first_term()} -> {last_term} with {len(checks.elections)} elections"),
        check("same entries applied in the same order", not conflicts,
              f"nodes applied different entries near index {conflicts[0]}" if conflicts else f"{len(checks.marks)} checkpoints matched"),
        check("acked writes survived", None if db is None else not lost,
              "could not read the db back" if db is None else
              f"{len(lost)} keys lost an acked write, e.g. {lost[:3]}" if lost else f"{len(db)} keys hold their last acked write"),
        check("no value out of thin air", None if db is None else not phantoms,
              "could not read the db back" if db is None else
              f"{len(phantoms)} keys hold a value nobody could have written, e.g. {phantoms[:3]}" if phantoms else "every value traces back to a write"),
        check("nodes agree at the end", verdict == "AGREE", verdict),
        check("serves writes again after the heal", recover_sec is not None,
              f"back {recover_sec}s after the heal" if recover_sec is not None else f"still down {RECOVER_MAX_SEC}s after everything was healed"),
    ]
    unsafe = any(result["ok"] is False for result in results[:7]) or verdict == "DIVERGED"
    passed = all(result["ok"] is True for result in results)

    kept_up = worst_lag_ms < 100 and checks.counts["notes_lost"] == 0
    results.append(check("test harness kept up", kept_up,
                         f"testy froze for up to {round(worst_lag_ms)}ms, nodes dropped {checks.counts['notes_lost']} telemetry lines"))

    seconds = measured_until - faults_began
    outages = checks.find_outages(checks.acks, faults_began, measured_until, checks.OUTAGE_MIN_SEC)
    could_have_led = viable_spans(measured_until)
    oos = sum(end - start for start, end in outages)
    oos_avoidable = checks.overlap(outages, could_have_led)

    for fault in chaos.faults:
        if fault["hit_leader"]: checks.time_the_fault(fault, measured_until)
    timed = [fault for fault in chaos.faults if fault["hit_leader"]]

    campaigns = [t for t, node_id, term in checks.elections if faults_began <= t <= measured_until]
    crowns = [t for t, node_id, term in checks.crowned if faults_began <= t <= measured_until]
    terms_then = [term for t, node_id, term in checks.crowned if t < faults_began]
    lat = sorted(ms for t, ms in checks.writes if faults_began <= t <= measured_until)

    healthy_per_sec = len([t for t, ms in checks.writes if faults_began - HEALTHY_SEC <= t < faults_began]) / HEALTHY_SEC

    metrics = {
        "seconds": round(seconds, 1),
        "availability": round(1 - oos / seconds, 4),
        "oos": round(oos, 2),
        "oos_avoidable": round(oos_avoidable, 2),
        "oos_unavoidable": round(oos - oos_avoidable, 2),
        "outages": len(outages),
        "longest_outage": round(max([end - start for start, end in outages], default=0), 2),
        "elections": len(campaigns),
        "elections_per_min": round(len(campaigns) / seconds * 60, 1),
        "leader_changes": len(crowns),
        "prevotes": len([t for t, node_id, term in checks.prevotes if faults_began <= t <= measured_until]),
        "term_growth": checks.max_term() - max(terms_then, default=0),
        "writes_per_sec": round(len(lat) / seconds, 1),
        "healthy_per_sec": round(healthy_per_sec, 1),
        "goodput": round(len(lat) / seconds / healthy_per_sec, 4) if healthy_per_sec else None,
        "p50": checks.pct(lat, 0.5) and round(checks.pct(lat, 0.5), 2),
        "p99": checks.pct(lat, 0.99) and round(checks.pct(lat, 0.99), 2),
        "max": lat[-1] and round(lat[-1], 2) if lat else None,
        "redirects": checks.totals["redirect"],
        "idks": checks.totals["idk"],
        "timeouts": checks.totals["timeout"],
        "leader_faults": len(timed),
        "detect_ms": checks.middle([fault["detect_ms"] for fault in timed]),
        "elect_ms": checks.middle([fault["elect_ms"] for fault in timed]),
        "ots_ms": checks.middle([fault["ots_ms"] for fault in timed]),
        "recover_sec": recover_sec,
        "snaps": checks.counts["snap_sent"],
    }
    if run["name"] == "links" and run["mode"] == "trial":
        metrics["ideal"] = round(checks.ideal_availability(run["x"]), 4)

    short = {key: run[key] for key in ("id", "mode", "name", "label", "flags", "seed", "hard", "seconds", "sweep", "x")}
    short.update({"verdict": verdict, "passed": passed, "metrics": metrics})

    return {
        "verdict": verdict, "passed": passed, "unsafe": unsafe, "checks": results, "metrics": metrics, "short": short,
        "nodes": nodes, "faults": chaos.faults, "window": [round(faults_began, 2), round(healed_at, 2), round(measured_until, 2)],
        "outages": [[round(start, 3), round(end, 3), round(checks.overlap([(start, end)], could_have_led), 3)] for start, end in outages],
    }

async def run_one(run):
    global is_test_over, phase, worst_lag_ms
    print(f"starting {run['id']} (seed {run['seed']})...", flush=True)

    rng = random.Random(run["seed"])
    flags = " ".join(f"{name}={value}" for name, value in sorted(run["flags"].items()))

    is_test_over = False
    worst_lag_ms = 0
    del frames[:], viable_log[:]
    vreqs_seen.clear()
    chaos.begin_run(flags, run["hard"])
    checks.begin_run()
    await send_to_browser({"run": run})
    watchers = [asyncio.create_task(watcher()) for watcher in (send_frames_4ever, watch_viable_4ever, watch_myself_4ever)]

    phase = "reset"
    if run["fresh"]:
        await reset_cluster(False)

    for node_id in range(NUM_NODES):
        await chaos.wake(node_id)
    is_cluster_up = await wait_until(lambda: all(checks.up[n] and checks.heard_from(n) for n in range(NUM_NODES)), 40)
    await chaos.wait_for_leader(15 if is_cluster_up else 0)

    phase = "warmup"
    clients = []
    for client_num in range(run["clients"]):
        task = asyncio.create_task(run_client(client_num, random.Random(rng.random()), run["keys"], run["think_ms"] / 1000))
        clients.append(task)
    for node_id in range(NUM_NODES):
        clients.append(asyncio.create_task(run_scout(node_id)))
    await asyncio.sleep(WARMUP_SEC)

    phase = "faults"
    faults_began = checks.now()
    if is_cluster_up:
        await break_things(rng, run)

    phase = "heal"
    await chaos.heal()
    healed_at = checks.now()
    await wait_until(lambda: not any(chaos.is_busy(n) for n in range(NUM_NODES)), 40)
    recover_sec = await wait_for_service(healed_at)
    await asyncio.sleep(SETTLE_SEC)
    measured_until = checks.now()

    phase = "drain"
    is_test_over = True
    await asyncio.gather(*clients)

    phase = "check"
    nodes = await check_agreement()
    answered = [node_id for node_id in range(NUM_NODES) if nodes[node_id]]
    most_applied = max(answered, key=lambda node_id: nodes[node_id]["applied"], default=None)
    db = await read_back(most_applied) if most_applied is not None else None

    summary = judge_run(run, nodes, db, faults_began, healed_at, measured_until, recover_sec)

    for watcher in watchers:
        watcher.cancel()
    frames.append(make_frame())
    await send_to_browser({"frame": frames[-1]})
    await send_to_browser({"summary": summary})

    os.makedirs(f"runs/{run['id']}", exist_ok=True)
    with open(f"runs/{run['id']}/summary.json", "w") as f: json.dump({"run": run, "summary": summary}, f)
    with open(f"runs/{run['id']}/frames.json", "w") as f: json.dump(frames, f)

    phase = "idle"
    if not summary["passed"]:
        await reset_cluster(summary["unsafe"])

    print(f"{run['id']}: {summary['verdict']}, {'passed' if summary['passed'] else 'FAILED'}", flush=True)
    return summary


def variant_name(flags):
    on = sorted(name if value == 1 else f"{name}={value}" for name, value in flags.items())
    return "+".join(on) or "baseline"

def new_run(what, **changes):
    run = dict(config, **changes)
    if run["seed"] is None: run["seed"] = secrets.randbits(48)
    run["label"] = run["label"] or variant_name(run["flags"])
    run["id"] = time.strftime("%Y%m%d-%H%M%S") + "-" + what
    run.setdefault("sweep", None)
    run.setdefault("x", None)
    return run

async def run_sweep():
    fault, x_name, xs, about = chaos.SWEEPS[config["name"]]
    xs = config["xs"] or xs
    turn = chaos.KNOBS.get(config["name"])

    sweep = {"id": time.strftime("%Y%m%d-%H%M%S") + "-sweep-" + config["name"], "name": config["name"], "about": about,
             "x_name": x_name, "xs": xs, "label": config["label"] or variant_name(config["flags"]),
             "flags": config["flags"], "seconds": config["seconds"], "hard": config["hard"], "points": []}
    await send_to_browser({"sweep": sweep})

    for i, x in enumerate(xs):
        for repeat in range(config["repeats"]):
            seed = None if config["seed"] is None else config["seed"] + i * 1000 + repeat
            flags = dict(config["flags"], **turn(x)) if turn else config["flags"]
            run = new_run(f"{config['name']}-{x}", mode="trial", seed=seed, fresh=True, sweep=sweep["id"], x=x,
                          flags=flags, label=sweep["label"])
            summary = await run_one(run)

            sweep["points"].append(dict(summary["metrics"], x=x, run=run["id"], verdict=summary["verdict"], passed=summary["passed"]))
            await send_to_browser({"sweep": sweep})

    os.makedirs(f"runs/{sweep['id']}", exist_ok=True)
    with open(f"runs/{sweep['id']}/sweep.json", "w") as f: json.dump(sweep, f)

def print_catalog():
    print(json.dumps({
        "scenarios": [{"name": name, "about": about, "seconds": seconds} for name, (run, about, seconds) in chaos.SCENARIOS.items()],
        "sweeps": [{"name": name, "about": about, "x_name": x_name, "xs": xs} for name, (run, x_name, xs, about) in chaos.SWEEPS.items()],
        "defaults": config,
    }))

async def main():
    global relay_ws, cluster_known

    relay_ws = await websockets.connect(RELAY_WS_URL, max_size=None)
    await relay_ws.send(json.dumps({"to": "relay", "msg": "i am testy"}))
    chaos.send_to_node = send_to_node

    cluster_known = asyncio.Event()
    for _ in range(NUM_NODES):
        born_dead_flags.append(asyncio.Event())
        done_flags.append(asyncio.Event())
        db_state_flags.append(asyncio.Event())

    watcher = asyncio.create_task(listen_to_relay())
    await cluster_known.wait()

    if config["mode"] == "sweep":
        await run_sweep()
    else:
        await run_one(new_run(config["name"] or "chaos"))

    watcher.cancel()
    await relay_ws.close()

    print("done", flush=True)

if __name__ == "__main__":
    if sys.argv[1:] == ["catalog"]:
        print_catalog()
    else:
        if len(sys.argv) > 1: config.update(json.loads(sys.argv[1]))
        asyncio.run(main())
