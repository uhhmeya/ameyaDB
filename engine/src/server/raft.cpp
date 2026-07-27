// raft.cpp
#include "../headers/globals.h"
#include <fstream>
#include <iostream>
#include <vector>
#include <unordered_set>

optional<entry> get_last_log_entry();

enum Raft_Role {
    FOLLOWER,
    CANDIDATE,
    LEADER
};

static const string RAFT_PATH = "../output/raft.txt";

static xnt curTerm;
static int vote;
static int leader;
static Raft_Role role;
static xnt commit_idx;
static unordered_set<int> in_votes;
static vector<xnt> sent_len;
static vector<xnt> ack_len;

void raft_init() {
    ifstream f(RAFT_PATH);

    // recover
    if (f.is_open()) {
        f >> curTerm >> vote;
        cerr << "[raft_init] recovered raft state" << endl;
    }

    // boot
    else {
        curTerm = 0;
        vote = -1;
        cerr << "[raft_init] No prev raft state found in " << RAFT_PATH << endl;
    }

    role = FOLLOWER;
    leader = -1;
    in_votes.clear();

    // leader only
    sent_len.assign(size(PEER_ADDRS), 0);
    ack_len.assign(size(PEER_ADDRS), 0);
    commit_idx = 0;
}

