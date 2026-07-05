// raft.cpp
#include "../headers/globals.h"
#include <fstream>
#include <iostream>
#include <vector>
#include <unordered_set>

enum Raft_Role {
    FOLLOWER,
    CANDIDATE,
    LEADER
};
enum Raft_ID {
    NOBODY = -1,
    node_0 = 0,
    node_1 = 1,
    node_2 = 2,
};

static const string RAFT_STATE_PATH = "../output/raft_state.txt";

static uint32_t term;
static Raft_ID vote;
static Raft_ID currentLeader;
static Raft_Role currentRole;
static uint32_t commit_idx;
static unordered_set<int> votesReceived;
static vector<uint32_t> sentLength;
static vector<uint32_t> ackedLength;

void raft_init() {

    // open raft
    ifstream f(RAFT_STATE_PATH);

    // recover state
    if (f.is_open()) {
        int raw_vote;
        f >> term >> raw_vote;
        vote = static_cast<Raft_ID>(raw_vote);
        cerr << "[raft_init] restored raft state" << endl;

    }

    // first boot
    else {
        term = 0;
        vote = NOBODY;
        cerr << "[raft_init] No prev raft state found in " << RAFT_STATE_PATH << endl;
    }

    // init
    commit_idx = 0;
    currentRole = FOLLOWER;
    currentLeader = NOBODY;

    // followers shouldn't have this
    votesReceived.clear();
    sentLength.assign(size(PEER_ADDRS), 0);
    ackedLength.assign(size(PEER_ADDRS), 0);
}