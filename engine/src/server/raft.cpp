// raft.cpp
#include "../headers/globals.h"
#include <fstream>
#include <iostream>
#include <vector>
#include <unordered_set>
#include <mutex>
#include <thread>

// from walsnap.cpp
xnt log_length();
xnt last_log_term();
int rand_sleep_timer_ms(int lo, int hi);

// from main.cpp
bool send_to_peer(int peer, const string& buf);

enum Raft_Role {
    FOLLOWER,
    CANDIDATE,
    LEADER
};

static const string RAFT_PATH = "../output/raft.txt";

// every static below is guarded by raft_mutex
static mutex raft_mutex;

// must survive crash
static xnt curTerm;
static int vote;

// restore
static int leader;
static Raft_Role role;
static xnt commit_idx;
static unordered_set<int> in_votes;
static vector<xnt> sent_len;
static vector<xnt> ack_len;

// time
static long long last_heard_ms;
static int election_timeout_ms;


static void persist_raft() {
    const string tmp = RAFT_PATH + ".tmp";
    {
        ofstream f(tmp, ios::trunc);
        f << curTerm << " " << vote << "\n";
        f.flush();
    }
    rename(tmp.c_str(), RAFT_PATH.c_str());
}


void raft_init() {

    curTerm = 0;
    vote = -1;

    ifstream f(RAFT_PATH);
    if (f.is_open() && (f >> curTerm >> vote))
        cerr << "[raft_init] recovered term=" << curTerm << " vote=" << vote << endl;
    else {
        curTerm = 0;
        vote = -1;
        cerr << "[raft_init] no prev raft state in " << RAFT_PATH << endl;
    }

    role = FOLLOWER;
    leader = -1;
    in_votes.clear();
    commit_idx = 0;

    // leader only
    sent_len.assign(NUM_NODES, 0);
    ack_len.assign(NUM_NODES, 0);

    last_heard_ms = now_ms();
    election_timeout_ms = rand_sleep_timer_ms(1500, 3000);
}



static void put(string& b, const void* p, size_t n) {
    b.append(static_cast<const char*>(p), n);
}


static string build_vote_request(xnt log_len, xnt last_term) {
    string b;
    char op = REQUEST_VOTE;
    put(b, &op, 1);
    put(b, &myNodeID, sizeof(myNodeID));
    put(b, &curTerm, sizeof(curTerm));
    put(b, &log_len, sizeof(log_len));
    put(b, &last_term, sizeof(last_term));
    return b;
}


void election_timer_loop() {
    while (true) {
        sleep_for(milliseconds(50));

        string msg;
        {
            // LOCK ORDER: raft_mutex, then log_mutex. never the reverse.
            lock_guard g(raft_mutex);

            if (role == LEADER) continue;                          // a leader never times itself out
            if (now_ms() - last_heard_ms < election_timeout_ms) continue;

            ++curTerm;                    // new era
            role = CANDIDATE;
            vote = myNodeID;              // vote for myself
            leader = -1;
            in_votes = { myNodeID };      // ...and count that vote
            persist_raft();               // term + vote hit disk BEFORE the request goes out

            msg = build_vote_request(log_length(), last_log_term());

            // restart the timer: if nobody wins, we time out again and try a higher term
            last_heard_ms = now_ms();
            election_timeout_ms = rand_sleep_timer_ms(1500, 3000);

            cerr << "[election] node " << myNodeID
                 << " standing for term " << curTerm << endl;
        }

        // send outside the lock -- write() can block on a dead peer
        for (int peer = 0; peer < NUM_NODES; ++peer)
            if (peer != myNodeID) send_to_peer(peer, msg);
    }
}

// called by whoever hears from a live leader (AppendEntries, slide 5/9)
void raft_note_leader_alive(int leader_id) {
    lock_guard g(raft_mutex);
    leader = leader_id;
    last_heard_ms = now_ms();
}