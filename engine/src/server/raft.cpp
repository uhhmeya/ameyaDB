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
static unordered_set<int> in_votes;
static vector<xnt> sent_len;
static vector<xnt> ack_len;
static vector<steady_clock::time_point> snap_sent;

static atomic<steady_clock::time_point> deadline{};

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
    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &log_idx, sizeof(log_idx));
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

static string build_AE(xnt term, xnt prefix_len, xnt prefix_term, xnt leader_commit, const vector<entry> &suffix) {
    char buf[1 + sizeof(int) + 5 * sizeof(xnt)];
    xnt n = suffix.size();
    buf[0] = APPEND_ENTRIES;
    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &prefix_len, sizeof(prefix_len));
    memcpy(&buf[1 + sizeof(int) + 2 * sizeof(xnt)], &prefix_term, sizeof(prefix_term));
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

static string build_AEres(xnt term, xnt ack, bool yes_or_no) {
    char buf[1 + sizeof(int) + 2 * sizeof(xnt) + 1];
    buf[0] = AERES;
    memcpy(&buf[1], &myNodeID, sizeof(myNodeID));
    memcpy(&buf[1 + sizeof(int)], &term, sizeof(term));
    memcpy(&buf[1 + sizeof(int) + sizeof(xnt)], &ack, sizeof(ack));
    buf[1 + sizeof(int) + 2 * sizeof(xnt)] = yes_or_no ? 1 : 0;
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

bool am_i_leader() {
    lock_guard g(ROCK);
    return role == LEADER;
}

int who_is_leader() {
    lock_guard g(ROCK);
    return leader;
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
    deadline = steady_clock::now() + milliseconds(rand_sleep_timer_ms(150, 300));
}

static void replicate(int follower) {
    xnt prefix_len = sent_len[follower];
    xnt prefix_term = 0;
    vector<entry> suffix;

    bool has_prefix = get_suffix(prefix_len, prefix_term, suffix);

    if (!has_prefix && steady_clock::now() - snap_sent[follower] > seconds(2)) {
        snap_sent[follower] = steady_clock::now();
        Psend(follower, build_SNAP(curTerm, read_snap()));
        return;
    }

    Psend(follower, build_AE(curTerm, prefix_len, prefix_term, commit_idx, suffix));
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

        // TODO : PREVOTE!!!
        curTerm++;
        role = CANDIDATE;
        votedFor = myNodeID;
        in_votes.clear();
        in_votes.insert(myNodeID);
        leader = NO_LEADER;

        save_tv();

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
        sleep_for(milliseconds(50));

        lock_guard g(ROCK);
        if (role != LEADER) continue;

        for (int node = 0; node < NUM_NODES; node++) {
            if (node == myNodeID) continue;
            replicate(node);
        }
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
    sent_len.assign(NUM_NODES, 0);
    ack_len.assign(NUM_NODES, 0);
    snap_sent.assign(NUM_NODES, steady_clock::time_point{});

    set_new_deadline();
    thread(Ethread).detach();
    thread(HBthread).detach();
}

bool onWrite(const string &k, const string &v) {
    unique_lock g(ROCK);

    if (role != LEADER) return false;

    xnt term_when_WR = curTerm;
    xnt idx = append_entry(k, v, curTerm);
    ack_len[myNodeID] = idx;

    for (int node = 0; node < NUM_NODES; node++) {
        if (node == myNodeID || sent_len[node] != idx - 1) continue;
        replicate(node);
    }

    for (int tries = 0; tries < 40 && commit_idx < idx && curTerm == term_when_WR; tries++)
        committed.wait_for(g, milliseconds(50));

    return commit_idx >= idx && curTerm == term_when_WR;
}

void onAE(int leader_id, xnt term, xnt prefix_len, xnt prefix_term, xnt leader_commit, const vector<entry> &suffix) {

    xnt term_when_AE;
    xnt ack = 0;
    bool yes_or_no = false;

    {
        lock_guard g(ROCK);

        // update
        if (term > curTerm) {
            curTerm = term;
            votedFor = NO_VOTE;
            save_tv();
        }

        if (term == curTerm) {
            role = FOLLOWER;
            leader = leader_id;
            set_new_deadline();
        }

        if (term == curTerm && log_ok(prefix_len, prefix_term)) {
            append_entries(suffix);
            ack = prefix_len + suffix.size();
            yes_or_no = true;

            xnt new_commit = min(leader_commit, ack);
            if (new_commit > commit_idx) {
                apply_entries(new_commit);
                commit_idx = new_commit;
            }
        } else {
            xnt log_len = get_log_idx();
            ack = log_len < prefix_len ? log_len : commit_idx;
        }

        term_when_AE = curTerm;
    }

    Psend(leader_id, build_AEres(term_when_AE, ack, yes_or_no));
}

void onAERes(int f_ID, xnt f_Term, xnt ack, bool yes_or_no) {
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

    if (yes_or_no && ack >= ack_len[f_ID]) {
        bool progress = ack > ack_len[f_ID];
        sent_len[f_ID] = ack;
        ack_len[f_ID] = ack;
        commit_log_entries();

        if (progress && ack < get_log_idx())
            replicate(f_ID);
    } else if (!yes_or_no && sent_len[f_ID] > ack) {
        sent_len[f_ID] = ack;
        replicate(f_ID);
    }
}

void onSnap(int leader_id, xnt term, const string &snap) {

    xnt term_when_SNAP;
    xnt ack = 0;
    bool yes_or_no = false;

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
            ack = install_snap(snap);
            commit_idx = max(commit_idx, ack);
            yes_or_no = true;
            set_new_deadline();
        }

        term_when_SNAP = curTerm;
    }

    Psend(leader_id, build_AEres(term_when_SNAP, ack, yes_or_no));
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

        xnt log_len = get_log_idx();
        sent_len.assign(NUM_NODES, log_len);
        ack_len.assign(NUM_NODES, 0);
        ack_len[myNodeID] = log_len;

        for (int node = 0; node < NUM_NODES; node++) {
            if (node == myNodeID) continue;
            replicate(node);
        }
    }
}
