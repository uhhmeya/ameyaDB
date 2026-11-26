import bisect
import itertools
import math
import time

NUM_NODES = 5
MAJORITY = NUM_NODES // 2 + 1
ALL_LINKS = [frozenset(pair) for pair in itertools.combinations(range(NUM_NODES), 2)]

FOLLOWER, CANDIDATE, LEADER, PRECANDIDATE = 0, 1, 2, 3
ROLE_NAMES = ["follower", "candidate", "leader", "precandidate"]

OUTAGE_MIN_SEC = 0.1


t0 = 0.0
up = {n: False for n in range(NUM_NODES)}
stats = {}
role_of = {}
wins = []
votes = []
terms = []
marks = []
elections = []
prevotes = []
crowned = []
events = []
new_events = []
counts = {"snap_sent": 0, "snap_installed": 0, "notes_lost": 0}

acks = []
writes = []
acked = {}
maybe = {}
tick = {"ok": 0, "redirect": 0, "idk": 0, "timeout": 0, "served": 0, "lat": []}
totals = {"ok": 0, "redirect": 0, "idk": 0, "timeout": 0}


def begin_run():
    global t0
    t0 = time.time()
    for record in (stats, role_of, acked, maybe):
        record.clear()
    for record in (wins, votes, terms, marks, elections, prevotes, crowned, events, new_events, acks, writes):
        del record[:]
    for name in counts: counts[name] = 0
    for name in totals: totals[name] = 0
    next_tick()

def now():
    return time.time() - t0

def next_tick():
    old = dict(tick)
    tick.update({"ok": 0, "redirect": 0, "idk": 0, "timeout": 0, "served": 0, "lat": []})
    return old

def take_new_events():
    news = list(new_events)
    del new_events[:]
    return news

def add_event(t, node, kind, term=0):
    event = [round(t, 3), node, kind, term]
    events.append(event)
    new_events.append(event)

def set_role(t, node, role, term):
    if role_of.get(node) == role: return
    role_of[node] = role
    add_event(t, node, ROLE_NAMES[role], term)

def on_node_msg(m):
    node, kind, words = m["node"], m["type"], m["msg"].split()
    t = m["wall_us"] / 1e6 - t0

    if kind == "stat":
        (term, role, leader, commit, applied, log_idx, snap_idx, apply_hash,
         conn, vreq, ae, snap, dropped, lost) = [int(word) for word in words[:14]]
        stats[node] = {"t": t, "at": time.time(), "term": term, "role": role, "leader": leader,
                       "commit": commit, "applied": applied, "log_idx": log_idx, "snap_idx": snap_idx,
                       "hash": apply_hash, "conn": conn, "vreq": vreq, "ae": ae, "snap": snap, "dropped": dropped}
        up[node] = True
        terms.append((node, term))
        if role == LEADER and (term, node) not in wins: wins.append((term, node))
        counts["notes_lost"] = max(counts["notes_lost"], lost)
        set_role(t, node, role, term)

    elif kind == "elec":
        term = int(words[0])
        terms.append((node, term))
        elections.append((t, node, term))
        set_role(t, node, CANDIDATE, term)

    elif kind == "prevote":
        prevotes.append((t, node, int(words[0])))

    elif kind == "leader":
        term = int(words[0])
        wins.append((term, node))
        crowned.append((t, node, term))
        set_role(t, node, LEADER, term)

    elif kind == "vote":
        term, candidate = int(words[0]), int(words[1])
        terms.append((node, term))
        votes.append((node, term, candidate))

    elif kind == "hash":
        marks.append((node, int(words[0]), int(words[1])))

    elif kind in ("snap_sent", "snap_installed"):
        counts[kind] += 1
        add_event(t, node, kind)

    elif kind == "booted":
        up[node] = True
        add_event(t, node, "up", int(words[2]))

    elif kind in ("crash", "cut"):
        add_event(t, node, kind)
    elif kind == "fault":
        add_event(t, node, words[0])

def on_node_down(node):
    up[node] = False
    stats.pop(node, None)
    role_of.pop(node, None)
    add_event(now(), node, "down")

def heard_from(node, within=1.0):
    return node in stats and time.time() - stats[node]["at"] < within

def leader_now():
    leader = None
    for node, stat in stats.items():
        if not up[node] or stat["role"] != LEADER or not heard_from(node): continue
        if leader is None or stat["term"] > stats[leader]["term"]: leader = node
    return leader

def max_term():
    return max([stat["term"] for stat in stats.values()], default=0)

def first_term():
    first = {}
    for node, term in terms:
        first.setdefault(node, term)
    return max(first.values(), default=0)

def wrote(key, seq, outcome, began, ended):
    tick[outcome] += 1
    totals[outcome] += 1

    if outcome == "ok":
        ms = (ended - began) * 1000
        acks.append(ended - t0)
        writes.append((ended - t0, ms))
        tick["lat"].append(ms)
        tick["served"] += 1
        acked.setdefault(key, []).append(seq)

    elif outcome != "redirect":
        maybe.setdefault(key, set()).add(seq)

def probed(key, seq, outcome, ended):
    if outcome == "ok":
        acks.append(ended - t0)
        tick["served"] += 1
        acked.setdefault(key, []).append(seq)
    else:
        maybe.setdefault(key, set()).add(seq)


def find_outages(ack_times, start, end, min_gap):
    outages = []
    last = start
    for t in ack_times:
        if t < start: continue
        if t > end: break
        if t - last > min_gap: outages.append((last, t))
        last = t
    if end - last > min_gap: outages.append((last, end))
    return outages

def longest_gap(ack_times, start, end, until):
    first = bisect.bisect_right(ack_times, start)
    last = bisect.bisect_right(ack_times, end)
    begins = [start] + ack_times[first:last]
    ends = ack_times[first:last + 1] + [until]
    return max(b - a for a, b in zip(begins, ends))

def overlap(spans_a, spans_b):
    total = 0.0
    for a0, a1 in spans_a:
        for b0, b1 in spans_b:
            total += max(0.0, min(a1, b1) - max(a0, b0))
    return total

def pct(sorted_values, q):
    if not sorted_values: return None
    rank = max(1, math.ceil(q * len(sorted_values)))
    return sorted_values[rank - 1]


def viable(alive, links):
    for node in alive:
        peers = sum(1 for link in links if node in link and link <= alive)
        if peers + 1 >= MAJORITY: return True
    return False

ideal_cache = {}

def ideal_availability(p):
    if p in ideal_cache: return ideal_cache[p]
    everyone = set(range(NUM_NODES))
    total = 0.0
    for up_count in range(len(ALL_LINKS) + 1):
        for links_up in itertools.combinations(ALL_LINKS, up_count):
            if viable(everyone, set(links_up)):
                total += (1 - p) ** up_count * p ** (len(ALL_LINKS) - up_count)
    ideal_cache[p] = total
    return total


def terms_with_two_leaders(wins):
    by_term = {}
    for term, node in wins:
        by_term.setdefault(term, set()).add(node)
    return sorted(term for term, nodes in by_term.items() if len(nodes) > 1)

def double_votes(votes):
    by_voter = {}
    for node, term, candidate in votes:
        by_voter.setdefault((node, term), set()).add(candidate)
    return sorted(voter for voter, candidates in by_voter.items() if len(candidates) > 1)

def term_went_back(seen):
    last = {}
    for node, term in seen:
        if term < last.get(node, 0): return (node, last[node], term)
        last[node] = term
    return None

def terms_from_nowhere(first, last, campaigns, restarts):
    return max(0, (last - first) - (campaigns + restarts))

def hash_conflicts(marks):
    by_idx = {}
    for node, idx, apply_hash in marks:
        by_idx.setdefault(idx, set()).add(apply_hash)
    return sorted(idx for idx, hashes in by_idx.items() if len(hashes) > 1)


def judge(nodes, conflicts):
    if conflicts: return "DIVERGED"

    by_applied = {}
    for node in nodes:
        if node is None: continue
        by_applied.setdefault(node["applied"], set()).add((node["hash"], node["digest"]))
    if any(len(states) > 1 for states in by_applied.values()): return "DIVERGED"

    if any(node is None for node in nodes): return "INCONCLUSIVE"
    if len(by_applied) > 1: return "LAGGING"
    if any(node["log_idx"] != node["applied"] for node in nodes): return "LAGGING"
    return "AGREE"

def judge_key(read, acked, maybe):
    if read is None: return "lost" if acked else "ok"
    if not read.isdigit(): return "phantom"

    seq = int(read)
    if acked and seq == acked[-1]: return "ok"
    if seq in maybe: return "ok"
    if seq in acked: return "lost"
    return "phantom"


STAMPS = {"crash": "cut", "partition": "connect", "pause": "pause", "limp": "limp"}

def when_it_hit(fault):
    stamp = STAMPS.get(fault["kind"])
    for t, node, kind, term in events:
        if node == fault["victim"] and kind == stamp and fault["t0"] - 0.05 <= t <= fault["t0"] + 2.0: return t
    return fault["t0"]

def time_the_fault(fault, until):
    began, old_term, victim = when_it_hit(fault), fault["term"], fault["victim"]
    fault["hit_at"] = round(began, 3)

    first_campaign = [t for t, node, term in elections if began <= t <= began + 15 and term > old_term and node != victim]
    first_crown = [t for t, node, term in crowned if began <= t <= began + 15 and term > old_term and node != victim]

    fault["detect_ms"] = round((first_campaign[0] - began) * 1000) if first_campaign else None
    fault["elect_ms"] = round((first_crown[0] - began) * 1000) if first_crown else None

    fault["ots_ms"] = round(longest_gap(acks, began - 0.05, began + 1.0, until) * 1000)

def middle(values):
    values = sorted(v for v in values if v is not None)
    return pct(values, 0.5)
