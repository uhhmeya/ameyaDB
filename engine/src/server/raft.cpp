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

// TODO ~ fix walsnap bug explained by claude!

enum Raft_Role {
    FOLLOWER,
    CANDIDATE,
    LEADER
};

static const string RAFT_PATH = "../output/raft.txt";
static const string RAFT_TMP_PATH = "../output/raft.tmp";

static mutex raft_mutex;

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

bool am_i_leader() {
    lock_guard g(raft_mutex);
    return role == LEADER;
}

int who_is_leader() {
    lock_guard g(raft_mutex);
    return leader;
}

void set_new_deadline() {
    deadline = steady_clock::now() + milliseconds(rand_sleep_timer_ms(150, 300));
}

void startE() {

}

static void Ethread() {
    while (true) {
        sleep_for(milliseconds(10));
        if (steady_clock::now() >= deadline.load()) {
            set_new_deadline();
            if (!am_i_leader())
                startE();
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

static void must(bool ok, const string &what) {
    if (!ok) {
        print("FATAL: " + what + ": " + string(strerror(errno)));
        abort();
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

void onAE(int leader_id, xnt term) {
    string log;
    {
        lock_guard g(raft_mutex);

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

xnt get_cur_term() {
    lock_guard g(raft_mutex);
    return curTerm;
}

