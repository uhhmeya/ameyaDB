# selftest.py : checks the checker. no cluster needed, just run `python3 selftest.py`
# every expected value here was worked out by hand, never by calling the code under test
import random

import chaos
import checks


def link(a, b):
    return frozenset((a, b))


# ---------------------------------------------------------------- out of service time

def test_gap_between_acks_longer_than_threshold_is_an_outage():
    acks = [0.00, 0.05, 0.10, 1.10, 1.15, 2.00]
    assert checks.find_outages(acks, 0.0, 2.0, 0.1) == [(0.10, 1.10), (1.15, 2.00)]

def test_silence_before_first_ack_and_after_last_ack_counts():
    assert checks.find_outages([1.0, 1.05], 0.0, 3.0, 0.1) == [(0.0, 1.0), (1.05, 3.0)]

def test_no_acks_at_all_is_one_long_outage():
    assert checks.find_outages([], 2.0, 9.0, 0.1) == [(2.0, 9.0)]

def test_acks_outside_the_window_are_ignored():
    acks = [0.5, 1.0, 1.05, 1.1, 5.0]
    assert checks.find_outages(acks, 1.0, 1.1, 0.1) == []

def test_longest_gap_is_the_silence_a_dead_leader_left_behind():
    # leader died at 10.0. one ack was already on its way, then nothing until the new leader's first at 10.185
    acks = [9.990, 9.996, 10.002, 10.185, 10.187, 10.190]
    assert abs(checks.longest_gap(acks, 9.95, 10.1, until=20.0) - 0.183) < 1e-9

def test_longest_gap_only_looks_at_silence_that_begins_inside_the_window():
    # 5.06 -> 6.5 is longer, but it began after the window closed
    acks = [4.99, 5.0, 5.01, 5.05, 5.06, 6.5, 8.5]
    assert abs(checks.longest_gap(acks, 4.995, 5.055, until=20.0) - 0.04) < 1e-9

def test_longest_gap_counts_silence_that_was_already_going_on_from_the_start():
    # nothing since 1.0. the fault at 5.0 landed in the middle of it, writes came back at 9.0
    assert checks.longest_gap([1.0, 9.0, 9.01], 5.0, 6.0, until=30.0) == 4.0

def test_longest_gap_runs_to_the_end_when_writes_never_come_back():
    assert checks.longest_gap([1.0, 2.0, 2.5], 2.4, 3.4, until=30.0) == 27.5

def test_longest_gap_with_no_acks_at_all_is_the_whole_wait():
    assert checks.longest_gap([], 5.0, 6.0, until=30.0) == 25.0

def test_overlap_only_counts_time_inside_both():
    outages = [(1.0, 3.0), (10.0, 11.0)]
    viable = [(0.0, 2.0), (10.5, 20.0)]
    assert checks.overlap(outages, viable) == 1.5


# ---------------------------------------------------------------- could anyone have led?

FULL_MESH = set(chaos.ALL_LINKS)

def test_full_mesh_is_viable():
    assert checks.viable({0, 1, 2, 3, 4}, FULL_MESH) is True

def test_star_is_viable_because_the_hub_reaches_a_majority():
    star = {link(2, 0), link(2, 1), link(2, 3), link(2, 4)}
    assert checks.viable({0, 1, 2, 3, 4}, star) is True

def test_pairs_only_is_not_viable():
    assert checks.viable({0, 1, 2, 3, 4}, {link(0, 1), link(2, 3)}) is False

def test_two_nodes_alive_is_not_viable_even_fully_connected():
    assert checks.viable({0, 1}, FULL_MESH) is False

def test_three_alive_and_connected_is_viable():
    assert checks.viable({0, 3, 4}, FULL_MESH) is True

def test_link_to_a_dead_node_does_not_count():
    # node 2 reaches 0 and 1, but 1 is down, so nobody has a majority
    assert checks.viable({0, 2}, {link(2, 0), link(2, 1)}) is False

def test_ideal_availability_at_the_extremes_and_at_a_coin_flip():
    assert checks.ideal_availability(0.0) == 1.0
    assert checks.ideal_availability(1.0) == 0.0
    # 26 of the 1024 link subsets leave every node with at most 1 link: 1 + 10 + 15
    assert abs(checks.ideal_availability(0.5) - (1 - 26 / 1024)) < 1e-12


# ---------------------------------------------------------------- raft safety

def test_two_nodes_winning_the_same_term_is_caught():
    wins = [(3, 1), (3, 1), (4, 2), (4, 0), (5, 0)]
    assert checks.terms_with_two_leaders(wins) == [4]

def test_same_node_reporting_its_win_twice_is_fine():
    assert checks.terms_with_two_leaders([(7, 2), (7, 2)]) == []

def test_voting_for_two_candidates_in_one_term_is_caught():
    votes = [(0, 5, 1), (0, 5, 1), (0, 5, 2), (1, 5, 2), (1, 6, 3)]
    assert checks.double_votes(votes) == [(0, 5)]

def test_term_going_backwards_is_caught():
    seen = [(0, 1), (0, 2), (1, 5), (0, 1)]
    assert checks.term_went_back(seen) == (0, 2, 1)

def test_terms_that_only_go_up_are_fine():
    assert checks.term_went_back([(0, 1), (1, 1), (0, 4), (1, 9)]) is None

def test_a_term_can_only_be_reached_through_elections():
    # 31 terms climbed, 32 campaigns seen: every step is explained
    assert checks.terms_from_nowhere(first=1, last=32, campaigns=32, restarts=0) == 0

def test_a_term_that_jumps_without_campaigns_is_caught():
    # the bug this was written for: garbage read off a wire became term 105538689 after 22 campaigns
    assert checks.terms_from_nowhere(first=1, last=105538689, campaigns=22, restarts=5) == 105538661

def test_each_restart_may_hide_one_campaign():
    # a node can die between saving its new term and telling the relay about it
    assert checks.terms_from_nowhere(first=10, last=14, campaigns=2, restarts=2) == 0
    assert checks.terms_from_nowhere(first=10, last=15, campaigns=2, restarts=2) == 1

def test_two_hashes_for_one_index_is_caught():
    marks = [(0, 500, 111), (1, 500, 111), (2, 500, 999), (0, 1000, 222), (1, 1000, 222)]
    assert checks.hash_conflicts(marks) == [500]


# ---------------------------------------------------------------- what the nodes say

def stat(node, role, seconds_in):
    # term role leader commit applied log_idx snap_idx apply_hash conn vreq ae snap dropped lost
    return {"node": node, "type": "stat", "wall_us": (checks.t0 + seconds_in) * 1e6, "msg": "5 %d -1 10 10 10 0 99 31 0 0 0 0 0" % role}

def test_a_node_asking_for_prevotes_shows_up_as_its_own_role():
    checks.begin_run()
    checks.on_node_msg(stat(2, role=3, seconds_in=1.0))
    assert checks.events[-1][1:3] == [2, "precandidate"]

def test_a_precandidate_is_never_mistaken_for_the_leader():
    checks.begin_run()
    checks.on_node_msg(stat(2, role=3, seconds_in=1.0))
    assert checks.leader_now() is None and checks.wins == []

def test_prevote_rounds_are_counted_apart_from_elections():
    checks.begin_run()
    checks.on_node_msg({"node": 1, "type": "prevote", "wall_us": (checks.t0 + 2.0) * 1e6, "msg": "7"})
    t, node, term = checks.prevotes[0]
    assert abs(t - 2.0) < 0.001 and (node, term) == (1, 7) and checks.elections == []


# ---------------------------------------------------------------- do the nodes agree?

def node(applied, hash_, digest=7, log_idx=None):
    return {"applied": applied, "term": 3, "keys": 10, "digest": digest, "hash": hash_,
            "log_idx": applied if log_idx is None else log_idx}

def test_all_five_identical_is_agree():
    assert checks.judge([node(90, 5)] * 5, []) == "AGREE"

def test_a_missing_reply_is_inconclusive():
    assert checks.judge([node(90, 5)] * 4 + [None], []) == "INCONCLUSIVE"

def test_same_index_different_hash_is_diverged():
    assert checks.judge([node(90, 5)] * 4 + [node(90, 6)], []) == "DIVERGED"

def test_same_index_different_db_is_diverged():
    assert checks.judge([node(90, 5)] * 4 + [node(90, 5, digest=8)], []) == "DIVERGED"

def test_a_node_that_is_only_behind_is_lagging():
    assert checks.judge([node(90, 5)] * 4 + [node(70, 2)], []) == "LAGGING"

def test_hash_conflict_seen_during_the_run_is_diverged_even_if_the_end_looks_equal():
    assert checks.judge([node(90, 5)] * 5, [500]) == "DIVERGED"

def test_an_uncommitted_tail_is_lagging_not_agree():
    assert checks.judge([node(90, 5)] * 4 + [node(90, 5, log_idx=93)], []) == "LAGGING"


# ---------------------------------------------------------------- did acked writes survive?

def test_last_acked_value_is_ok():
    assert checks.judge_key("7", acked=[3, 7], maybe=set()) == "ok"

def test_older_acked_value_means_the_newer_ack_was_lost():
    assert checks.judge_key("3", acked=[3, 7], maybe=set()) == "lost"

def test_missing_key_that_was_acked_is_lost():
    assert checks.judge_key(None, acked=[3], maybe=set()) == "lost"

def test_missing_key_that_was_never_acked_is_ok():
    assert checks.judge_key(None, acked=[], maybe={4}) == "ok"

def test_a_write_that_timed_out_may_have_landed():
    assert checks.judge_key("9", acked=[3, 7], maybe={5, 9}) == "ok"

def test_a_value_nobody_could_have_written_is_a_phantom():
    assert checks.judge_key("8", acked=[3, 7], maybe={5}) == "phantom"

def test_garbage_value_is_a_phantom():
    assert checks.judge_key("v12x", acked=[3], maybe=set()) == "phantom"


# ---------------------------------------------------------------- small math

def test_percentile_is_nearest_rank():
    ten = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert checks.pct(ten, 0.50) == 5
    assert checks.pct(ten, 0.99) == 10
    assert checks.pct([], 0.5) is None


# ---------------------------------------------------------------- what each node gets told

def test_healthy_node_is_told_nothing_special():
    assert chaos.wanted(0, cuts={}, gray={}, disks={}, hard=True) == ("all", {}, 0)

def test_firewall_cut_removes_the_peer_from_the_allow_list():
    cuts = {1: {link(0, 1)}, 2: {link(0, 3)}}
    assert chaos.wanted(0, cuts, {}, {}, hard=True) == ("24", {}, 0)
    assert chaos.wanted(4, cuts, {}, {}, hard=True) == ("all", {}, 0)

def test_node_cut_from_everyone_is_told_none():
    cuts = {1: {link(2, 0), link(2, 1), link(2, 3), link(2, 4)}}
    assert chaos.wanted(2, cuts, {}, {}, hard=True) == ("none", {}, 0)

def test_soft_cut_keeps_the_firewall_open_and_drops_every_msg_instead():
    cuts = {1: {link(0, 1)}}
    assert chaos.wanted(0, cuts, {}, {}, hard=False) == ("all", {1: (0, 0, 100)}, 0)
    assert chaos.wanted(1, cuts, {}, {}, hard=False) == ("all", {0: (0, 0, 100)}, 0)

def test_gray_link_only_touches_the_sending_side():
    gray = {5: {(0, 1): (120, 30, 0)}}
    assert chaos.wanted(0, {}, gray, {}, hard=True) == ("all", {1: (120, 30, 0)}, 0)
    assert chaos.wanted(1, {}, gray, {}, hard=True) == ("all", {}, 0)

def test_overlapping_faults_keep_the_worst_of_each_knob():
    gray = {5: {(0, 1): (120, 30, 0)}, 6: {(0, 1): (40, 0, 25)}}
    disks = {7: {0: 20}, 8: {0: 90}}
    assert chaos.wanted(0, {}, gray, disks, hard=True) == ("all", {1: (120, 30, 25)}, 90)


def test_the_timeout_sweep_turns_both_raft_timers_together():
    # heartbeats stay 3 to an election timeout, like the 50ms / 150ms the nodes default to
    assert chaos.KNOBS["timeout"](150) == {"election_ms": 150, "heartbeat_ms": 50}
    assert chaos.KNOBS["timeout"](60) == {"election_ms": 60, "heartbeat_ms": 20}

def test_a_sweep_that_only_breaks_things_turns_no_switch():
    assert "links" not in chaos.KNOBS

def test_every_knob_belongs_to_a_sweep_that_exists():
    assert set(chaos.KNOBS) <= set(chaos.SWEEPS)


# ---------------------------------------------------------------- shapes

def test_bridge_is_two_triangles_that_share_one_node():
    # {0, 1} and {3, 4} can't see each other, node 2 sees all four
    kept = set(chaos.ALL_LINKS) - chaos.split([0, 1], [3, 4])
    assert kept == {link(0, 1), link(0, 2), link(1, 2), link(2, 3), link(2, 4), link(3, 4)}
    assert checks.viable({0, 1, 2, 3, 4}, kept) is True

def test_star_cuts_every_link_that_misses_the_hub():
    cut = chaos.star(2)
    assert len(cut) == 6
    assert link(2, 0) not in cut and link(0, 1) in cut and link(3, 4) in cut

def test_line_keeps_only_neighbours():
    cut = chaos.line([3, 0, 4, 1, 2])
    kept = set(chaos.ALL_LINKS) - cut
    assert kept == {link(3, 0), link(0, 4), link(4, 1), link(1, 2)}

def test_split_cuts_exactly_the_links_that_cross():
    cut = chaos.split([0, 1], [2, 3, 4])
    assert len(cut) == 6
    assert link(0, 1) not in cut and link(2, 4) not in cut and link(1, 3) in cut

def test_island_cuts_all_four_links_of_one_node():
    assert chaos.island(3) == {link(3, 0), link(3, 1), link(3, 2), link(3, 4)}

def test_lottery_at_zero_and_one():
    rng = random.Random(1)
    assert chaos.lottery(rng, 0.0) == set()
    assert chaos.lottery(rng, 1.0) == set(chaos.ALL_LINKS)

def test_lottery_cuts_about_p_of_the_links():
    rng = random.Random(7)
    cut = sum(len(chaos.lottery(rng, 0.3)) for _ in range(2000))
    assert 0.27 < cut / 20000 < 0.33


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {type(e).__name__} {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
