// raft.cpp
#include "../headers/globals.h"
#include <fstream>
#include <vector>
#include <unordered_set>

static const string RAFT_STATE_PATH = "../output/raft_state.txt";

static uint32_t currentTerm = 0;
static int votedFor = -1;
static uint32_t commit_idx = 0;
static Raft_Role currentRole = FOLLOWER;
static int currentLeader = -1;
static unordered_set<int> votesReceived;
static vector<uint32_t> sentLength;
static vector<uint32_t> ackedLength;

void raft_init() {
    ifstream f(RAFT_STATE_PATH);

    if (f.is_open()) {
        f >> currentTerm >> votedFor;
        cerr << "[raft_init] restored raft state" << endl;
    }

    else {
        currentTerm = 0;
        votedFor = -1;
        cerr << "[raft_init] No prev raft state found in " << RAFT_STATE_PATH << endl;
    }

    commit_idx = 0;
    currentRole = FOLLOWER;
    currentLeader = -1;
    votesReceived.clear();
    sentLength.assign(size(PEER_ADDRS), 0);
    ackedLength.assign(size(PEER_ADDRS), 0);
}