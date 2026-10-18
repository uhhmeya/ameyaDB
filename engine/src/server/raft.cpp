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

enum Raft_Role {
    FOLLOWER,
    CANDIDATE,
    LEADER
};

static const string RAFT_PATH = "../output/raft.txt";
static const string RAFT_TMP_PATH = "../output/raft.tmp";

static mutex ROCK;

// restore
static xnt curTerm;
static int vote;

// new
static int leader;
static Raft_Role role;
static xnt commit_idx;
static unordered_set<int> in_votes;
static vector<xnt> sent_len;
static vector<xnt> ack_len;

static atomic<steady_clock::time_point> deadline{};

static void must(bool ok, const string &what)
{
    if (!ok) {
        print("FATAL: " + what + ": " + string(strerror(errno)));
        abort();
    }
}

static string build_Vreq(xnt term, xnt log_idx, xnt last_log_term) {
    return to_string(static_cast<int>(VREQ)) + " "
        + to_string(myNodeID) + " "
        + to_string(term) + " "
        + to_string(log_idx) + " "
        + to_string(last_log_term) + "\n";
}

static string build_Vres(xnt term, bool granted) {
    return to_string(static_cast<int>(VRES)) + " "
        + to_string(myNodeID) + " "
        + to_string(term) + " "
        + to_string(granted ? 1 : 0) + "\n";
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
        send_to_peer(node, msg);
    }
}

static void save_tv() {
    const string tv = to_string(curTerm) + " " + to_string(vote) + "\n";

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

static void startELEC() {

    xnt term_when_ELEC_started;
    xnt log_index;
    xnt term_of_last_log_entry;

    // LOCK
    {
        lock_guard g(ROCK);

        if (role == LEADER) return;

        curTerm++;
        role = CANDIDATE;
        vote = myNodeID;
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
        if (steady_clock::now() >= deadline.load()) {
            set_new_deadline();
            startELEC();
        }
    }
}

void raft_init() {

    // init
    curTerm = 0;
    vote = NO_VOTE;

    // reboot
    ifstream f(RAFT_PATH);
    bool isReboot = f.is_open() && (f >> curTerm >> vote);

    // all
    role = FOLLOWER;
    leader = NO_LEADER;
    in_votes.clear();
    commit_idx = 0;
    sent_len.assign(NUM_NODES, 0);
    ack_len.assign(NUM_NODES, 0);

    set_new_deadline();
    thread(Ethread).detach();
}

void onAE(int leader_id, xnt term) {
    string log;
    {
        lock_guard g(ROCK);

        // stale leader
        if (term < curTerm)
            return;

        // update
        if (term > curTerm) {
            curTerm = term;
            vote = NO_VOTE;
            save_tv();
        }

        role = FOLLOWER;
        leader = leader_id;
        set_new_deadline();
    }
}

void onVR(int c_ID, xnt c_Term, xnt c_LogIDX, xnt c_LogTERM) {

    xnt term_when_VR;
    bool granted;

    // LOCK
    {
        lock_guard g(ROCK);

        // newer term
        if (c_Term > curTerm) {
            curTerm = c_Term;
            role = FOLLOWER;
            vote = NO_VOTE;
            leader = NO_LEADER;
            save_tv();
        }

        // my log
        xnt my_LogIDX;
        xnt my_LogTERM;
        get_log_idx_and_last_log_term(my_LogIDX, my_LogTERM);

        bool logOk = (c_LogTERM > my_LogTERM) || (c_LogTERM == my_LogTERM && c_LogIDX >= my_LogIDX);
        bool termOk = (c_Term == curTerm);
        bool voteOk = (vote == NO_VOTE || vote == c_ID);

        granted = termOk && logOk && voteOk;

        // vote
        if (granted) {
            vote = c_ID;
            save_tv();
            set_new_deadline();
        }

        term_when_VR = curTerm;
    }
    // LOCK

    send_to_peer(c_ID, build_Vres(term_when_VR, granted));
}