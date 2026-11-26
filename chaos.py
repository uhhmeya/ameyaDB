import asyncio
import math
import time

import checks
from checks import NUM_NODES, ALL_LINKS

send_to_node = None
flags = ""
hard = True

cuts = {}
gray = {}
disks = {}
told = {}
busy_until = {}
faults = []
changed = set()


def begin_run(new_flags, new_hard):
    global flags, hard
    flags, hard = new_flags, new_hard
    for record in (cuts, gray, disks, told, busy_until):
        record.clear()
    del faults[:]
    changed.clear()


def link(a, b):
    return frozenset((a, b))

def island(node):
    return {l for l in ALL_LINKS if node in l}

def star(hub):
    return {l for l in ALL_LINKS if hub not in l}

def line(order):
    kept = {link(a, b) for a, b in zip(order, order[1:])}
    return set(ALL_LINKS) - kept

def split(side_a, side_b):
    return {link(a, b) for a in side_a for b in side_b}

def lottery(rng, p):
    return {l for l in ALL_LINKS if rng.random() < p}

def both_ways(a, b, knobs):
    return {(a, b): knobs, (b, a): knobs}


def wanted(node, cuts, gray, disks, hard):
    blocked, links = set(), {}

    for cut in cuts.values():
        for l in cut:
            if node not in l: continue
            (peer,) = l - {node}
            if hard: blocked.add(peer)
            else: links[peer] = (0, 0, 100)

    for fault in gray.values():
        for (sender, receiver), (delay, jitter, drop) in fault.items():
            if sender != node: continue
            old = links.get(receiver, (0, 0, 0))
            links[receiver] = (max(old[0], delay), max(old[1], jitter), max(old[2], drop))

    stall = max([fault.get(node, 0) for fault in disks.values()], default=0)

    allowed = "".join(str(peer) for peer in range(NUM_NODES) if peer != node and peer not in blocked)
    if len(allowed) == NUM_NODES - 1: allowed = "all"
    if allowed == "": allowed = "none"
    return allowed, links, stall

async def tell(node, again=False):
    allowed, links, stall = wanted(node, cuts, gray, disks, hard)
    old_allowed, old_links, old_stall = (None, {}, 0) if again else told.get(node, (None, {}, 0))

    if allowed != old_allowed:
        await send_to_node(node, "connect " + allowed)
    for peer in range(NUM_NODES):
        knobs = links.get(peer, (0, 0, 0))
        if peer != node and knobs != old_links.get(peer, (0, 0, 0)):
            await send_to_node(node, "link %d %d %d %d" % ((peer,) + knobs))
    if stall != old_stall:
        await send_to_node(node, "disk %d" % stall)

    told[node] = (allowed, links, stall)

async def tell_everyone():
    for node in range(NUM_NODES):
        await tell(node)

async def wake(node):
    await send_to_node(node, "flags " + flags)
    await tell(node, again=True)


def record(label, kind, nodes, deadly=False):
    leader = checks.leader_now()
    fault = {"id": len(faults), "label": label, "kind": kind, "nodes": list(nodes),
             "t0": round(checks.now(), 3), "t1": None, "term": checks.max_term(),
             "hit_leader": deadly and leader in nodes, "victim": leader}
    faults.append(fault)
    changed.add(fault["id"])
    return fault

async def start(label, kind, nodes=(), cut=None, slow=None, stall=None, deadly=False):
    fault = record(label, kind, nodes, deadly)
    if cut: cuts[fault["id"]] = set(cut)
    if slow: gray[fault["id"]] = dict(slow)
    if stall: disks[fault["id"]] = dict(stall)
    await tell_everyone()
    return fault

async def stop(fault):
    for active in (cuts, gray, disks):
        active.pop(fault["id"], None)
    fault["t1"] = round(checks.now(), 3)
    changed.add(fault["id"])
    await tell_everyone()

async def hold(seconds, label, kind, nodes=(), cut=None, slow=None, stall=None, deadly=False):
    fault = await start(label, kind, nodes, cut, slow, stall, deadly)
    await asyncio.sleep(seconds)
    await stop(fault)

def is_busy(node):
    return not checks.up[node] or busy_until.get(node, 0) > time.time()

async def crash(node, seconds):
    if is_busy(node): return None
    fault = record("crash node%d for %.1fs" % (node, seconds), "crash", [node], deadly=True)
    fault["t1"] = round(fault["t0"] + seconds, 3)
    busy_until[node] = time.time() + seconds
    checks.up[node] = False
    await send_to_node(node, "terminate %.2f" % seconds)
    return fault

async def pause(node, ms):
    if is_busy(node): return None
    fault = record("freeze node%d for %dms" % (node, ms), "pause", [node], deadly=ms >= 500)
    fault["t1"] = round(fault["t0"] + ms / 1000, 3)
    busy_until[node] = time.time() + ms / 1000
    await send_to_node(node, "pause %d" % ms)
    return fault

async def limp(node, stop_ms, run_ms, seconds):
    if is_busy(node): return None
    fault = record("node%d limps: frozen %dms of every %dms" % (node, stop_ms, stop_ms + run_ms), "limp", [node])
    fault["t1"] = round(fault["t0"] + seconds, 3)
    await send_to_node(node, "limp %d %d %d" % (stop_ms, run_ms, seconds * 1000))
    return fault

async def heal():
    for active in (cuts, gray, disks):
        active.clear()
    for fault in faults:
        if fault["t1"] is None:
            fault["t1"] = round(checks.now(), 3)
            changed.add(fault["id"])
    await tell_everyone()

def take_changed():
    news = [faults[fault_id] for fault_id in sorted(changed)]
    changed.clear()
    return news


def dead_links():
    dead = set()
    for cut in cuts.values():
        dead |= cut
    for fault in gray.values():
        for (sender, receiver), (delay, jitter, drop) in fault.items():
            if drop >= 100: dead.add(link(sender, receiver))
    return dead

def viable_now():
    alive = {node for node in range(NUM_NODES) if checks.up[node] and busy_until.get(node, 0) < time.time()}
    return checks.viable(alive, set(ALL_LINKS) - dead_links())

def link_codes():
    all_cuts = set()
    for cut in cuts.values():
        all_cuts |= cut

    codes = ""
    for sender in range(NUM_NODES):
        for receiver in range(NUM_NODES):
            delay, drop = 0, 0
            for fault in gray.values():
                knobs = fault.get((sender, receiver), (0, 0, 0))
                delay, drop = max(delay, knobs[0]), max(drop, knobs[2])

            if sender == receiver: codes += "-"
            elif link(sender, receiver) in all_cuts: codes += "1" if hard else "2"
            elif drop >= 100: codes += "2"
            elif drop > 0: codes += "3"
            elif delay > 0: codes += "4"
            else: codes += "0"
    return codes


async def wait_for_leader(timeout=15):
    give_up = time.time() + timeout
    while time.time() < give_up:
        leader = checks.leader_now()
        if leader is not None: return leader
        await asyncio.sleep(0.05)
    return 0

def victim(rng, leader_bias=0.5):
    leader = checks.leader_now()
    if leader is not None and rng.random() < leader_bias: return leader
    return rng.randrange(NUM_NODES)

def others(rng, *taken):
    rest = [node for node in range(NUM_NODES) if node not in taken]
    rng.shuffle(rest)
    return rest

def log_uniform(rng, lo, hi):
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))

def how_long(rng, cap, lo=0.3, hi=15):
    return max(0.2, min(cap, log_uniform(rng, lo, hi)))


async def rand_crash(rng, cap):
    seconds = how_long(rng, cap, 0.3, 12)
    if await crash(victim(rng), seconds): await asyncio.sleep(seconds)

async def rand_majority_crash(rng, cap):
    seconds = how_long(rng, cap, 1, 6)
    for node in others(rng)[:3]:
        await crash(node, seconds)
    await asyncio.sleep(seconds)

async def rand_island(rng, cap):
    node = victim(rng)
    await hold(how_long(rng, cap), "node%d cut off from everyone" % node, "partition", [node], cut=island(node), deadly=True)

async def rand_split(rng, cap):
    nodes = others(rng)
    await hold(how_long(rng, cap), "split %s | %s" % (nodes[:2], nodes[2:]), "partition", nodes[:2], cut=split(nodes[:2], nodes[2:]), deadly=True)

async def rand_links(rng, cap):
    cut = lottery(rng, 0.3)
    await hold(how_long(rng, cap), "%d random links cut" % len(cut), "partition", [], cut=cut)

async def rand_shape(rng, cap):
    nodes = others(rng)
    if rng.random() < 0.5:
        await hold(how_long(rng, cap), "star around node%d" % nodes[0], "partition", [], cut=star(nodes[0]))
    else:
        await hold(how_long(rng, cap), "chain " + "-".join(map(str, nodes)), "partition", [], cut=line(nodes))

async def rand_flap(rng, cap):
    a, b = others(rng)[:2]
    give_up = time.time() + how_long(rng, cap, 2, 15)
    while time.time() < give_up:
        await hold(rng.uniform(0.1, 0.8), "link %d-%d flaps" % (a, b), "partition", [], cut={link(a, b)})
        await asyncio.sleep(rng.uniform(0.1, 0.8))

async def rand_pause(rng, cap):
    ms = int(min(cap * 1000, log_uniform(rng, 100, 5000)))
    if await pause(victim(rng), ms): await asyncio.sleep(ms / 1000)

async def rand_limp(rng, cap):
    seconds = int(how_long(rng, cap, 2, 15)) + 1
    if await limp(victim(rng), rng.choice([40, 80, 120, 200]), 20, seconds): await asyncio.sleep(seconds)

async def rand_slow(rng, cap):
    node, delay = victim(rng), int(log_uniform(rng, 20, 800))
    slow = {(node, peer): (delay, delay // 3, 0) for peer in range(NUM_NODES) if peer != node}
    await hold(how_long(rng, cap), "everything node%d sends is %dms late" % (node, delay), "gray", [node], slow=slow)

async def rand_lossy(rng, cap):
    node, drop = victim(rng), rng.randint(5, 60)
    slow = {}
    for peer in range(NUM_NODES):
        if peer != node: slow.update(both_ways(node, peer, (0, 0, drop)))
    await hold(how_long(rng, cap), "node%d's links lose %d%% of msgs" % (node, drop), "gray", [node], slow=slow)

async def rand_one_way(rng, cap):
    node = victim(rng)
    if rng.random() < 0.5:
        slow = {(peer, node): (0, 0, 100) for peer in range(NUM_NODES) if peer != node}
        await hold(how_long(rng, cap), "node%d goes deaf: it sends, nothing reaches it" % node, "one way", [node], slow=slow, deadly=True)
    else:
        slow = {(node, peer): (0, 0, 100) for peer in range(NUM_NODES) if peer != node}
        await hold(how_long(rng, cap), "node%d goes mute: it hears, nothing it sends arrives" % node, "one way", [node], slow=slow, deadly=True)

async def rand_disk(rng, cap):
    node, stall = victim(rng), int(log_uniform(rng, 5, 300))
    await hold(how_long(rng, cap), "node%d's disk takes %dms per write" % (node, stall), "gray", [node], stall={node: stall})

MENU = [
    (rand_crash, 3), (rand_majority_crash, 0.5), (rand_island, 2), (rand_split, 2), (rand_links, 2),
    (rand_shape, 1), (rand_flap, 1.5), (rand_pause, 2), (rand_limp, 1), (rand_slow, 2),
    (rand_lossy, 1.5), (rand_one_way, 1.5), (rand_disk, 1.5),
]

async def random_chaos(rng, seconds, gap):
    give_up = time.time() + seconds
    running = []
    while True:
        await asyncio.sleep(rng.expovariate(1 / gap))
        left = give_up - time.time()
        if left < 1: break
        fault = rng.choices([f for f, weight in MENU], [weight for f, weight in MENU])[0]
        running.append(asyncio.create_task(fault(rng, left)))
    await asyncio.gather(*running)


async def leader_crashes(rng, seconds):
    give_up = time.time() + seconds
    while time.time() + 4 < give_up:
        L = await wait_for_leader()
        await crash(L, 3)
        await asyncio.sleep(8)

async def figure8(rng, seconds):
    give_up = time.time() + seconds
    while time.time() + 3 < give_up:
        L = await wait_for_leader(5)
        await asyncio.sleep(rng.uniform(0.05, 0.5))
        if sum(not is_busy(node) for node in range(NUM_NODES)) >= 4:
            await crash(L, rng.uniform(1, 3))

async def rolling_restart(rng, seconds):
    for node in range(NUM_NODES):
        await crash(node, 15)
        await asyncio.sleep(15)
        while not checks.up[node]: await asyncio.sleep(0.1)
        await asyncio.sleep(10)

async def full_outage(rng, seconds):
    for node in range(NUM_NODES):
        await crash(node, 5)
    await asyncio.sleep(seconds)

async def majority_crash(rng, seconds):
    L = await wait_for_leader()
    for node in [L] + others(rng, L)[:2]:
        await crash(node, seconds / 2)
    await asyncio.sleep(seconds)

async def split_brain(rng, seconds):
    L = await wait_for_leader()
    rest = others(rng, L)
    await hold(seconds, "leader node%d stuck in the minority with node%d" % (L, rest[0]), "partition", [L], cut=split([L, rest[0]], rest[1:]), deadly=True)

async def partial_partition(rng, seconds):
    L = await wait_for_leader()
    f = others(rng, L)[0]
    await hold(seconds, "only the link between leader node%d and node%d is cut" % (L, f), "partition", [L, f], cut={link(L, f)})

async def leader_link_flap(rng, seconds):
    give_up = time.time() + seconds
    while time.time() + 1 < give_up:
        L = await wait_for_leader(2)
        f = others(rng, L)[0]
        await hold(0.4, "link between leader node%d and node%d drops" % (L, f), "partition", [L, f], cut={link(L, f)})
        await asyncio.sleep(0.4)

async def bridge(rng, seconds):
    L = await wait_for_leader()
    a, b, c, d = others(rng, L)
    await hold(seconds, "nodes %d+%d and nodes %d+%d can't see each other, all four see node%d" % (L, a, c, d, b),
               "partition", [], cut=split([L, a], [c, d]))

async def returning_follower(rng, seconds):
    give_up = time.time() + seconds
    while time.time() + 8 < give_up:
        L = await wait_for_leader()
        f = others(rng, L)[0]
        await hold(4, "follower node%d is cut off from everyone, then it comes back" % f, "partition", [f], cut=island(f))
        await asyncio.sleep(4)

async def quorum_loss(rng, seconds):
    L = await wait_for_leader()
    hub = others(rng, L)[0]
    await hold(seconds, "everyone only reaches node%d, but node%d leads" % (hub, L), "partition", [L], cut=star(hub), deadly=True)

async def constrained_election(rng, seconds):
    L = await wait_for_leader()
    hub, a, b, c = others(rng, L)

    lag = await start("node%d falls behind: the leader's msgs reach it 100ms late" % hub, "gray", [hub], slow={(L, hub): (100, 0, 0)})
    await asyncio.sleep(3)

    cut = island(L) | split([a], [b, c]) | split([b], [c])
    stuck = await start("leader node%d is gone, node%d reaches everyone but has the oldest log" % (L, hub), "partition", [L], cut=cut, deadly=True)
    await stop(lag)
    await asyncio.sleep(seconds)
    await stop(stuck)

async def chained(rng, seconds):
    L = await wait_for_leader()
    a, b, c, d = others(rng, L)
    order = [a, L, b, c, d]
    await hold(seconds, "chain %s: node%d and node%d never hear leader node%d" % ("-".join(map(str, order)), c, d, L), "partition", [c, d], cut=line(order))

async def stragglers(rng, seconds):
    L = await wait_for_leader()
    a, b, c, d = others(rng, L)
    kept = {link(L, a), link(L, b), link(a, b), link(c, b), link(d, L)}
    await hold(seconds, "node%d only reaches node%d, node%d only reaches leader node%d" % (c, b, d, L), "partition", [c, d], cut=set(ALL_LINKS) - kept)

async def prevote_trap(rng, seconds):
    L = await wait_for_leader()
    a, b, c, d = others(rng, L)
    await crash(d, seconds)
    kept = {link(a, b), link(a, c), link(b, c), link(L, b)}
    await hold(seconds, "leader node%d only reaches node%d, node%d is down" % (L, b, d), "partition", [L], cut=set(ALL_LINKS) - kept, deadly=True)

async def deaf_leader(rng, seconds):
    L = await wait_for_leader()
    slow = {(peer, L): (0, 0, 100) for peer in range(NUM_NODES) if peer != L}
    await hold(seconds, "leader node%d goes deaf: its heartbeats arrive, no reply ever reaches it" % L, "one way", [L], slow=slow, deadly=True)

async def mute_leader(rng, seconds):
    L = await wait_for_leader()
    slow = {(L, peer): (0, 0, 100) for peer in range(NUM_NODES) if peer != L}
    await hold(seconds, "leader node%d goes mute: it hears everyone, nothing it sends arrives" % L, "one way", [L], slow=slow, deadly=True)

async def deaf_follower(rng, seconds):
    L = await wait_for_leader()
    f = others(rng, L)[0]
    slow = {(peer, f): (0, 0, 100) for peer in range(NUM_NODES) if peer != f}
    await hold(seconds, "follower node%d goes deaf: it never hears the leader but everyone hears it" % f, "one way", [f], slow=slow)

async def pause_leader(rng, seconds):
    give_up = time.time() + seconds
    while time.time() + 4 < give_up:
        L = await wait_for_leader()
        await pause(L, 3000)
        await asyncio.sleep(8)

async def pause_follower(rng, seconds):
    give_up = time.time() + seconds
    while time.time() + 5 < give_up:
        L = await wait_for_leader()
        await pause(others(rng, L)[0], 1000)
        await asyncio.sleep(5)

async def limping_leader(rng, seconds):
    L = await wait_for_leader()
    await limp(L, 80, 20, int(seconds))
    await asyncio.sleep(seconds)

async def slow_disk_leader(rng, seconds):
    L = await wait_for_leader()
    await hold(seconds, "leader node%d's disk takes 50ms per write" % L, "gray", [L], stall={L: 50})

async def slow_leader(rng, seconds):
    L = await wait_for_leader()
    slow = {(L, peer): (120, 30, 0) for peer in range(NUM_NODES) if peer != L}
    await hold(seconds, "everything leader node%d sends is 120-150ms late" % L, "gray", [L], slow=slow)

async def lossy_mesh(rng, seconds):
    slow = {(a, b): (0, 0, 20) for a in range(NUM_NODES) for b in range(NUM_NODES) if a != b}
    await hold(seconds, "every link loses 20% of msgs", "gray", [], slow=slow)

SCENARIOS = {
    "leader_crashes":       (leader_crashes, "kill the leader every 8s. clean numbers for failure detection + out of service time", 40),
    "figure8":              (figure8, "kill each new leader moments after it wins, so logs fill with entries nobody committed", 40),
    "rolling_restart":      (rolling_restart, "the original test: every node down for 15s, one after another", 140),
    "full_outage":          (full_outage, "all 5 nodes die at once and come back from disk", 15),
    "majority_crash":       (majority_crash, "leader + 2 followers die, the 2 left can't do anything", 20),
    "split_brain":          (split_brain, "leader on the small side of a 2|3 split keeps taking writes it can never commit", 20),
    "partial_partition":    (partial_partition, "one cut link between the leader and one follower. both still reach everyone else", 30),
    "bridge":               (bridge, "two pairs of nodes that can't see each other, joined by one node that sees everyone", 30),
    "returning_follower":   (returning_follower, "a follower is cut off for 4s, votes for itself the whole time, then walks back in with a huge term", 40),
    "leader_link_flap":     (leader_link_flap, "a link that keeps dropping, always between the current leader and some follower", 30),
    "quorum_loss":          (quorum_loss, "star: every node only reaches one hub, and the hub is not the leader", 30),
    "constrained_election": (constrained_election, "the only node that reaches a majority has the oldest log, so raft can't elect it", 30),
    "chained":              (chained, "chain: the nodes at the far end never hear the leader and keep calling elections", 30),
    "stragglers":           (stragglers, "two nodes each hang on by one link (Howard + Abraham's no-stable-leader case)", 30),
    "prevote_trap":         (prevote_trap, "leader keeps one follower and loses its majority. the case PreVote alone makes worse", 30),
    "deaf_leader":          (deaf_leader, "one way: the leader's heartbeats arrive but it never hears a reply", 30),
    "mute_leader":          (mute_leader, "one way: the leader hears everyone but nothing it sends arrives", 30),
    "deaf_follower":        (deaf_follower, "one way: a follower never hears the leader, yet its vote requests reach everyone", 30),
    "pause_leader":         (pause_leader, "leader frozen for 3s with its sockets open, then it wakes up thinking it still leads", 40),
    "pause_follower":       (pause_follower, "gray: a follower frozen for 1s wakes up with its election timer long expired and the leader's heartbeats unread", 40),
    "limping_leader":       (limping_leader, "gray: leader only runs 20% of the time. slow enough to hurt, alive enough to stay", 30),
    "slow_disk_leader":     (slow_disk_leader, "gray: every write on the leader's disk takes 50ms", 30),
    "slow_leader":          (slow_leader, "gray: the leader's msgs arrive 120-150ms late, right under the election timeout", 30),
    "lossy_mesh":           (lossy_mesh, "gray: every link silently loses 20% of msgs", 30),
}


async def link_lottery(rng, seconds, p):
    fault = await start("every link down with probability %.2f, redrawn every 2s" % p, "partition", [], cut=lottery(rng, p))
    give_up = time.time() + seconds
    while time.time() + 2 < give_up:
        await asyncio.sleep(2)
        cuts[fault["id"]] = lottery(rng, p)
        await tell_everyone()
    await asyncio.sleep(max(0, give_up - time.time()))
    await stop(fault)

async def blinking_link(rng, seconds, p):
    give_up = time.time() + seconds
    while time.time() + 0.5 < give_up:
        if rng.random() < p:
            L = await wait_for_leader(1)
            f = others(rng, L)[0]
            await hold(0.5, "link between leader node%d and node%d blinks" % (L, f), "partition", [L, f], cut={link(L, f)})
        else:
            await asyncio.sleep(0.5)

async def msg_loss(rng, seconds, pct):
    slow = {(a, b): (0, 0, int(pct)) for a in range(NUM_NODES) for b in range(NUM_NODES) if a != b}
    await hold(seconds, "every link loses %d%% of msgs" % pct, "gray", [], slow=slow if pct else None)

async def late_leader(rng, seconds, ms):
    L = await wait_for_leader()
    slow = {(L, peer): (int(ms), 0, 0) for peer in range(NUM_NODES) if peer != L}
    await hold(seconds, "everything leader node%d sends is %dms late" % (L, ms), "gray", [L], slow=slow if ms else None)

async def frozen_leader(rng, seconds, stop_ms):
    L = await wait_for_leader()
    if stop_ms: await limp(L, int(stop_ms), 20, int(seconds))
    await asyncio.sleep(seconds)

async def stalled_disk(rng, seconds, ms):
    L = await wait_for_leader()
    await hold(seconds, "leader node%d's disk takes %dms per write" % (L, ms), "gray", [L], stall={L: int(ms)} if ms else None)

async def napping_follower(rng, seconds, ms):
    give_up = time.time() + seconds
    while time.time() + 3 < give_up:
        L = await wait_for_leader()
        if ms: await pause(others(rng, L)[0], int(ms))
        await asyncio.sleep(3)

async def crashes_and_blips(rng, seconds, election_ms):
    give_up = time.time() + seconds
    next_crash = time.time() + 8
    while time.time() + 1 < give_up:
        L = await wait_for_leader(2)

        if time.time() > next_crash:
            await crash(L, 3)
            next_crash = time.time() + 8
            await asyncio.sleep(4)
            continue

        f = others(rng, L)[0]
        await hold(0.12, "link between leader node%d and node%d blips" % (L, f), "partition", [L, f], cut={link(L, f)})
        await asyncio.sleep(rng.uniform(0.5, 1.5))

SWEEPS = {
    "links": (link_lottery, "chance a link is down", [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
              "every one of the 10 links is down with probability x, redrawn every 2s. compared against the best any protocol could do"),
    "blink": (blinking_link, "chance per 0.5s that the leader loses a link", [0, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8],
              "intermittent partial partition: the leader keeps losing one link for half a second"),
    "loss":  (msg_loss, "% of msgs lost", [0, 1, 2, 5, 10, 20, 30, 40],
              "every link silently loses x% of msgs"),
    "delay": (late_leader, "leader delay ms", [0, 20, 50, 80, 110, 140, 200, 300, 500],
              "everything the leader sends arrives x ms late. the election timeout starts at 150ms"),
    "limp":  (frozen_leader, "ms the leader is frozen out of every x+20", [0, 20, 50, 80, 110, 140, 200, 300],
              "the leader only runs 20ms at a time. how slow can it get before anyone replaces it?"),
    "disk":  (stalled_disk, "leader disk ms per write", [0, 2, 5, 10, 20, 50, 100, 200],
              "every write to the leader's disk takes x ms"),
    "nap":   (napping_follower, "ms a follower is frozen", [0, 50, 100, 150, 200, 250, 300, 400, 600, 1000],
              "a follower freezes for x ms every 3s. past the election timeout it wakes up sure the leader is gone"),
    "timeout": (crashes_and_blips, "election timeout ms", [40, 60, 90, 120, 150, 250, 400],
              "the nodes run with election timeout x to 2x. the leader dies every 8s and loses one link for 120ms about once a second"),
    "tour":  (None, "scenario", list(SCENARIOS),
              "every handmade edge case, one after another. the table a paper would print"),
}

KNOBS = {
    "timeout": lambda x: {"election_ms": int(x), "heartbeat_ms": int(x) // 3},
}
