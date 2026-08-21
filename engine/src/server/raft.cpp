// raft.cpp
#include "../headers/globals.h"
#include "../headers/threads.h"

#include <fstream>
#include <iostream>
#include <vector>
#include <unordered_set>
#include <mutex>
#include <thread>
#include <unistd.h>
#include <fcntl.h>

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

// utils
static void write_and_fsync_or_die(const string &path, const string &data) {
    int file = open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (file < 0 || write(file, data.data(), data.size()) != (ssize_t)data.size() || fsync(file) != 0) {
        print("FATAL: could not write+fsync " + path + ": " + string(strerror(errno)));
        abort();
    }
    close(file);
}
static void rename_or_die(const string &tmp, const string &path) {
    if (rename(tmp.c_str(), path.c_str()) != 0) {
        print("FATAL: could not rename " + tmp + " -> " + path + ": " + string(strerror(errno)));
        abort();
    }
}
static void fsync_parent_dir_or_die(const string &path) {
    size_t slash = path.find_last_of('/');
    string dir = (slash == string::npos) ? "." : path.substr(0, slash);

    int dirfile = open(dir.c_str(), O_RDONLY | O_DIRECTORY);
    if (dirfile < 0 || fsync(dirfile) != 0) {
        print("FATAL: could not fsync directory " + dir + ": " + string(strerror(errno)));
        abort();
    }
    close(dirfile);
}

// caller holds raft_mutex
static void reset_election_timer() {
    last_heard_ms = now_ms();
    election_timeout_ms = rand_sleep_timer_ms(1500, 3000);
}

void raft_init() {
    ifstream f(RAFT_PATH);
    if (f.is_open() && (f >> curTerm >> vote))
        print("recovered t=" + to_string(curTerm) + " v=" + to_string(vote));
    else {
        curTerm = 0;
        vote = -1;
        print("FIRST BOOT!!!");
    }

    role = FOLLOWER;
    leader = -1;
    in_votes.clear();
    commit_idx = 0;
    sent_len.assign(NUM_NODES, 0);
    ack_len.assign(NUM_NODES, 0);
    reset_election_timer();
}

static void save_termVote() {
    const string raft_tmp = RAFT_PATH + ".tmp";
    const string termVote = to_string(curTerm) + " " + to_string(vote) + "\n";

    // puts termVote into raft_tmp
    // fsync's raft_tmp to disk
    write_and_fsync_or_die(raft_tmp, termVote);

    // swaps raft_tmp with raft_txt
    rename_or_die(raft_tmp, RAFT_PATH);

    // commits new raft_txt by fsync'ing parent dir
    fsync_parent_dir_or_die(RAFT_PATH);
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
        xnt term_snap = 0;
        {
            lock_guard g(raft_mutex);   // LOCK ORDER: raft_mutex then log_mutex

            // keep the clock fresh while we lead, so stepping down doesn't
            // fire an election on the very next tick
            if (role == LEADER) { reset_election_timer(); continue; }
            if (now_ms() - last_heard_ms < election_timeout_ms) continue;

            ++curTerm;
            role = CANDIDATE;
            vote = myNodeID;
            leader = -1;
            in_votes = { myNodeID };
            save_termVote();             // disk before the wire

            msg = build_vote_request(get_log_length(), get_last_log_term());
            term_snap = curTerm;

            reset_election_timer();     // split vote -> retry at a higher term
        }

        print("standing t=" + to_string(term_snap));   // don't hold raft_mutex over cout

        for (int peer = 0; peer < NUM_NODES; ++peer)
            if (peer != myNodeID) send_to_peer(peer, msg);
    }
}

void raft_on_append_entries(int leader_id, xnt term) {
    string log;
    {
        lock_guard g(raft_mutex);

        if (term < curTerm) return;          // stale leader: ignore, don't touch the timer

        if (term > curTerm) {
            curTerm = term;
            vote = -1;
            save_termVote();
        }

        role = FOLLOWER;                     // candidate concedes, old leader steps down
        leader = leader_id;
        reset_election_timer();
        log = "leader=" + to_string(leader_id) + " t=" + to_string(term);
    }
    print(log);
}


// called by whoever hears from a live leader (AppendEntries, slide 5/9)
void raft_note_leader_alive(int leader_id) {
    lock_guard g(raft_mutex);
    leader = leader_id;
    last_heard_ms = now_ms();
}