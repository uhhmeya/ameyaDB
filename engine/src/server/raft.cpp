#include "../headers/globals.h"
#include "../headers/threads.h"
#include <cstring>
#include <cerrno>
#include <fstream>
#include <iostream>
#include <vector>
#include <unordered_set>
#include <unistd.h>
#include <fcntl.h>
#include <chrono>
#include <condition_variable>
#include <random>
# include <thread>
#include <algorithm>
#include <limits>

enum Raft_Role {
    FOLLOWER,
    CANDIDATE,
    LEADER
};

static const string RAFT_PATH = "../output/raft.txt";
static const string RAFT_TMP_PATH = "../output/raft.tmp";

static mutex ROCK;
static condition_variable committed;

// restore
static xnt curTerm;
static int votedFor;

// new
static int leader;
static Raft_Role role;
static xnt commit_idx;
static xnt leaders_commit_idx;
static unordered_set<int> in_votes;
static vector<xnt> sent_len;
static vector<xnt> ack_len;
static vector<steady_clock::time_point> snap_sent;

static atomic<steady_clock::time_point> deadline{};

// research switches, testy sets these for every run
static bool prevote_on() { return get_flag("prevote", 0) == 1; }
static bool checkquorum_on() { return get_flag("checkquorum", 0) == 1; }

// timers in ms. a sweep can turn these, nothing else changes them
static int election_ms() { return get_flag("election_ms", 150); }
static int heartbeat_ms() { return get_flag("heartbeat_ms", 50); }

static void must(bool ok, const string &what)
{
    if (!ok) {
        print("FATAL: " + what + ": " + string(strerror(errno)));
        abort();
    }
}

static string build_Vreq(xnt term, xnt log_idx, xnt last_log_term) {
    char buf[1 + sizeof(int) + 3 * sizeof(xnt)];
    buf[0] = VREQ;
    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));

    // term
    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));

    // log idx
    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &log_idx, sizeof(log_idx));

    // last log term in old batch
    memcpy(&buf[1 + sizeof(int) + 2 * sizeof(xnt)], &last_log_term, sizeof(last_log_term));
    return string(buf, sizeof(buf));
}

static string build_Vres(xnt term, bool yes_or_no) {
    char buf[1 + sizeof(int) + sizeof(xnt) + 1];
    buf[0] = VRES;
    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
    buf[1 + sizeof(int) + sizeof(xnt)] = yes_or_no ? 1 : 0;
    return string(buf, sizeof(buf));
}

static string build_AE(xnt term, xnt last_log_idx_in_old_batch, xnt last_log_term_in_old_batch,
    xnt leader_commit, const vector<entry> &suffix) {
    char buf[1 + sizeof(int) + 5 * sizeof(xnt)];
    xnt n = suffix.size();
    buf[0] = APPEND_ENTRIES;
    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &last_log_idx_in_old_batch, sizeof(last_log_idx_in_old_batch));
    memcpy(&buf[1 + sizeof(int) + 2 * sizeof(xnt)], &last_log_term_in_old_batch, sizeof(last_log_term_in_old_batch));
    memcpy(&buf[1 + sizeof(int) + 3 * sizeof(xnt)], &leader_commit, sizeof(leader_commit));
    memcpy(&buf[1 + sizeof(int) + 4 * sizeof(xnt)], &n, sizeof(n));

    string msg(buf, sizeof(buf));
    for (const entry &e : suffix) {
        xnt k_len = e.wr.k.size();
        xnt v_len = e.wr.v.size();
        msg.append(reinterpret_cast<const char *>(&k_len), sizeof(k_len));
        msg.append(e.wr.k);
        msg.append(reinterpret_cast<const char *>(&v_len), sizeof(v_len));
        msg.append(e.wr.v);
        msg.append(reinterpret_cast<const char *>(&e.stats), sizeof(e.stats));
        msg.append(reinterpret_cast<const char *>(&e.log_index), sizeof(e.log_index));
        msg.append(reinterpret_cast<const char *>(&e.term), sizeof(e.term));
        msg.append(reinterpret_cast<const char *>(&e.checksum), sizeof(e.checksum));
    }
    return msg;
}

static string build_AEres(xnt term, xnt last_log_idx_in_next_old_batch, bool was_ae_accepted) {
    char buf[1 + sizeof(int) + 2 * sizeof(xnt) + 1];
    buf[0] = AERES;
    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &last_log_idx_in_next_old_batch, sizeof(last_log_idx_in_next_old_batch));
    buf[1 + sizeof(int) + 2 * sizeof(xnt)] = was_ae_accepted ? 1 : 0;
    return string(buf, sizeof(buf));
}

static string build_SNAP(xnt term, const string &snap) {
    char buf[1 + sizeof(int) + 2 * sizeof(xnt)];
    xnt snap_len = snap.size();
    buf[0] = SNAP;
    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &snap_len, sizeof(snap_len));
    return string(buf, sizeof(buf)) + snap;
}

xnt get_cur_term() {
    lock_guard g(ROCK);
    return curTerm;
}

xnt get_commit_idx() {
    lock_guard g(ROCK);
    return commit_idx;
}

bool am_i_leader() {
    lock_guard g(ROCK);
    return role == LEADER;
}

int who_is_leader() {
    lock_guard g(ROCK);
    return leader;
}

// follower is only done once it has everything the leader committed
bool am_i_caught_up() {
    lock_guard g(ROCK);
    return role == LEADER || commit_idx >= leaders_commit_idx;
}

// leader can't cut entries a connected follower still needs
xnt get_oldest_idx_a_follower_needs() {
    lock_guard g(ROCK);

    xnt oldest_idx = numeric_limits<xnt>::max();
    if (role != LEADER) return oldest_idx;

    for (int node = 0; node < NUM_NODES; node++) {
        bool is_connected = my_fd_to[node].load() >= 0;
        if (node == myNodeID || !is_connected) continue;
        oldest_idx = min(oldest_idx, sent_len[node]);
    }
    return oldest_idx;
}

static void broadcast(const string &msg) {
    for (int node = 0; node < NUM_NODES; node++) {
        if (node == myNodeID) continue;
        Psend(node, msg);
    }
}

static void save_tv() {
    const string tv = to_string(curTerm) + " " + to_string(votedFor) + "\n";

    // open raft.tmp
    int fd = open(RAFT_TMP_PATH.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    must(fd >= 0, "open raft.tmp");

    // write tv to raft.tmp
    must(write(fd, tv.data(), tv.size()) == (ssize_t)tv.size(), "write raft.tmp");

    // fsync raft.tmp
    must(fsync(fd) == 0, "fsync raft.tmp");
    close(fd);

    // rename to raft.txt
    must(rename(RAFT_TMP_PATH.c_str(), RAFT_PATH.c_str()) == 0, "rename");

    // make rename survive crash
    int d = open("../output", O_RDONLY | O_DIRECTORY);
    must(d >= 0, "open output dir");
    must(fsync(d) == 0, "fsync output dir");
    close(d);
}

static void set_new_deadline() {
    deadline = steady_clock::now() + milliseconds(rand_sleep_timer_ms(election_ms(), 2 * election_ms()));
}

static void replicate(int follower) {
    xnt last_log_idx_in_old_batch = sent_len[follower];
    xnt last_log_term_in_old_batch = 0;
    vector<entry> suffix;

    bool suffix_starts_in_snap = !get_suffix(last_log_idx_in_old_batch, last_log_term_in_old_batch, suffix);
    bool snap_sent_recently = steady_clock::now() - snap_sent[follower] <= seconds(10);
    bool is_connected = my_fd_to[follower].load() >= 0;

    // if snap was not sent to this node in the last 10 seconds
    if (suffix_starts_in_snap && !snap_sent_recently && is_connected) {
        snap_sent[follower] = steady_clock::now();
        note("snap_sent", to_string(follower));
        xnt term_when_SNAP = curTerm;
        thread([follower, term_when_SNAP] {
            Psend(follower, build_SNAP(term_when_SNAP, read_snap()));
        }).detach();
        return;
    }

    Psend(follower, build_AE(curTerm, last_log_idx_in_old_batch, last_log_term_in_old_batch, commit_idx, suffix));
}

static void commit_log_entries() {
    vector<xnt> acks = ack_len;
    sort(acks.begin(), acks.end(), greater<>());
    xnt ready = acks[NUM_NODES / 2];

    if (ready > commit_idx && get_term(ready) == curTerm) {
        apply_entries(ready);
        commit_idx = ready;
        committed.notify_all();
    }
}

static void startELEC() {

    xnt term_when_ELEC_started;
    xnt log_index;
    xnt term_of_last_log_entry;

    // LOCK
    {
        lock_guard g(ROCK);

        if (steady_clock::now() < deadline.load()) return;
        set_new_deadline();
        if (role == LEADER) return;

        // TODO : PREVOTE!!! (only when prevote_on()). note("prevote", term) puts every round on the dashboard
        curTerm++;
        role = CANDIDATE;
        votedFor = myNodeID;
        in_votes.clear();
        in_votes.insert(myNodeID);
        leader = NO_LEADER;

        save_tv();
        note("elec", to_string(curTerm));

        term_when_ELEC_started = curTerm;
        get_log_idx_and_last_log_term(log_index, term_of_last_log_entry);
    }
    // LOCK

    broadcast(build_Vreq(term_when_ELEC_started, log_index, term_of_last_log_entry));
}

static void Ethread() {
    while (true) {
        sleep_for(milliseconds(10));
        if (steady_clock::now() >= deadline.load())
            startELEC();
    }
}

static void HBthread() {
    while (true) {
        sleep_for(milliseconds(heartbeat_ms()));

        lock_guard g(ROCK);
        if (role != LEADER) continue;

        // TODO : CHECKQUORUM!!! (only when checkquorum_on())
        for (int node = 0; node < NUM_NODES; node++) {
            if (node == myNodeID) continue;
            replicate(node);
        }
    }
}

// dashboard reads one of these from every node 4 times a second
static void STATthread() {
    while (true) {
        sleep_for(milliseconds(250));

        lock_guard g(ROCK);
        note("stat", to_string(curTerm) + " " + to_string(role) + " " + to_string(leader) + " "
                   + to_string(commit_idx) + " " + log_stat() + " " + net_stat() + " " + to_string(get_notes_lost()));
    }
}

void raft_init() {

    // init
    curTerm = 0;
    votedFor = NO_VOTE;

    // reboot
    ifstream f(RAFT_PATH);
    bool isReboot = f.is_open() && (f >> curTerm >> votedFor);

    // all
    role = FOLLOWER;
    leader = NO_LEADER;
    in_votes.clear();
    commit_idx = get_applied_idx();
    leaders_commit_idx = 0;
    sent_len.assign(NUM_NODES, 0);
    ack_len.assign(NUM_NODES, 0);
    snap_sent.assign(NUM_NODES, steady_clock::time_point{});

    set_new_deadline();
    thread(Ethread).detach();
    thread(HBthread).detach();
    thread(STATthread).detach();
}

bool onWrite(const string &k, const string &v) {
    unique_lock g(ROCK);

    if (role != LEADER) return false;

    xnt term_when_WR = curTerm;
    xnt log_idx = append_entry(k, v, curTerm);
    ack_len[myNodeID] = log_idx;

    for (int node = 0; node < NUM_NODES; node++) {
        if (node == myNodeID || sent_len[node] != log_idx - 1) continue;
        replicate(node);
    }

    for (int tries = 0; tries < 40 && commit_idx < log_idx && curTerm == term_when_WR; tries++)
        committed.wait_for(g, milliseconds(50));

    return commit_idx >= log_idx && curTerm == term_when_WR;
}

void onAE(int leader_id, xnt term, xnt last_log_idx_in_old_batch, xnt last_log_term_in_old_batch,
    xnt leader_commit, const vector<entry> &suffix) {

    xnt term_when_AE;
    xnt last_log_idx_in_next_old_batch = 0;
    bool are_we_accepting_ae = false;

    {
        lock_guard g(ROCK);

        if (term > curTerm) {
            curTerm = term;
            votedFor = NO_VOTE;
            save_tv();
        }

        if (term == curTerm) {
            role = FOLLOWER;
            leader = leader_id;
            leaders_commit_idx = leader_commit;
            set_new_deadline();
        }

        if (term == curTerm && log_ok(last_log_idx_in_old_batch, last_log_term_in_old_batch)) {
            append_entries(suffix);
            last_log_idx_in_next_old_batch = last_log_idx_in_old_batch + suffix.size();
            are_we_accepting_ae = true;

            xnt new_commit = min(leader_commit, last_log_idx_in_next_old_batch);
            if (new_commit > commit_idx) {
                apply_entries(new_commit);
                commit_idx = new_commit;
            }
        } else {
            xnt log_len = get_log_idx();
            last_log_idx_in_next_old_batch = log_len < last_log_idx_in_old_batch ? log_len : commit_idx;
        }

        term_when_AE = curTerm;
    }

    Psend(leader_id, build_AEres(term_when_AE, last_log_idx_in_next_old_batch, are_we_accepting_ae));
}

void onAERes(int f_ID, xnt f_Term, xnt last_log_idx_in_next_old_batch, bool was_ae_accepted) {
    lock_guard g(ROCK);

    if (f_Term < curTerm)
        return;

    if (f_Term > curTerm) {
        curTerm = f_Term;
        role = FOLLOWER;
        votedFor = NO_VOTE;
        leader = NO_LEADER;
        save_tv();
        set_new_deadline();
        return;
    }

    if (role != LEADER || f_ID < 0 || f_ID >= NUM_NODES)
        return;

    if (was_ae_accepted && last_log_idx_in_next_old_batch >= ack_len[f_ID]) {
        bool progress = last_log_idx_in_next_old_batch > ack_len[f_ID];
        sent_len[f_ID] = last_log_idx_in_next_old_batch;
        ack_len[f_ID] = last_log_idx_in_next_old_batch;
        commit_log_entries();

        if (progress && last_log_idx_in_next_old_batch < get_log_idx())
            replicate(f_ID);
    } else if (!was_ae_accepted && sent_len[f_ID] > last_log_idx_in_next_old_batch) {
        sent_len[f_ID] = last_log_idx_in_next_old_batch;
        replicate(f_ID);
    }
}

void onSnap(int leader_id, xnt term, const string &snap) {

    xnt term_when_SNAP;
    xnt last_log_idx_in_next_old_batch = 0;
    bool was_ae_accepted = false;

    {
        lock_guard g(ROCK);

        if (term > curTerm) {
            curTerm = term;
            votedFor = NO_VOTE;
            save_tv();
        }

        if (term == curTerm) {
            role = FOLLOWER;
            leader = leader_id;
            last_log_idx_in_next_old_batch = install_snap(snap);
            note("snap_installed", to_string(last_log_idx_in_next_old_batch));
            commit_idx = max(commit_idx, last_log_idx_in_next_old_batch);
            was_ae_accepted = true;
            set_new_deadline();
        }

        term_when_SNAP = curTerm;
    }

    Psend(leader_id, build_AEres(term_when_SNAP, last_log_idx_in_next_old_batch, was_ae_accepted));
}

void onVReq(int c_ID, xnt c_Term, xnt c_LogIDX, xnt c_LogTERM) {

    xnt term_when_VR;
    bool yes_or_no;

    // LOCK
    {
        lock_guard g(ROCK);

        // newer term
        if (c_Term > curTerm) {
            curTerm = c_Term;
            role = FOLLOWER;
            votedFor = NO_VOTE;
            leader = NO_LEADER;
            save_tv();
        }

        // my log
        xnt my_LogIDX;
        xnt my_LogTERM;
        get_log_idx_and_last_log_term(my_LogIDX, my_LogTERM);

        bool logOk = (c_LogTERM > my_LogTERM) || (c_LogTERM == my_LogTERM && c_LogIDX >= my_LogIDX);
        bool termOk = (c_Term == curTerm);
        bool voteOk = (votedFor == NO_VOTE || votedFor == c_ID);

        yes_or_no = termOk && logOk && voteOk;

        // vote
        if (yes_or_no) {
            votedFor = c_ID;
            save_tv();
            set_new_deadline();
            note("vote", to_string(curTerm) + " " + to_string(c_ID));
        }

        term_when_VR = curTerm;
    }
    // LOCK

    Psend(c_ID, build_Vres(term_when_VR, yes_or_no));
}

void onVRes(int c_ID, xnt c_Term, bool was_vote_granted) {
    lock_guard g(ROCK);

    if (c_Term < curTerm)
        return;

    if (c_Term > curTerm) {
        curTerm = c_Term;
        role = FOLLOWER;
        votedFor = NO_VOTE;
        leader = NO_LEADER;
        in_votes.clear();
        save_tv();
        set_new_deadline();
        return;
    }

    // if no
    if (role != CANDIDATE || !was_vote_granted)
        return;

    in_votes.insert(c_ID);

    if (in_votes.size() >= NUM_NODES / 2 + 1) {
        role = LEADER;
        leader = myNodeID;
        note("leader", to_string(curTerm));

        xnt log_len = get_log_idx();
        sent_len.assign(NUM_NODES, log_len);
        ack_len.assign(NUM_NODES, 0);

        ack_len[myNodeID] = append_entry(NO_OP, NO_OP, curTerm);

        for (int node = 0; node < NUM_NODES; node++) {
            if (node == myNodeID) continue;
            replicate(node);
        }
    }
}
