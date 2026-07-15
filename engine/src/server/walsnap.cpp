#include "../headers/globals.h"
#include <fstream>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <unordered_set>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <cstdio>

static const string SNAP_DIR_PATH = "../output/snaps/";
static const string WAL_PATH      = "../output/wal.txt";

static unordered_map<string, string> db;
static shared_mutex db_mutex;
static ofstream wal;
static mutex wal_mutex;
static str_arr_2D prev_snap_arr;
static str_arr_1D dk;
static mutex dk_mutex;


static string serialize_entry(const entry& e) {
    return e.wr.k                                + " " +
           e.wr.v                                + " " +
           to_string(e.stats.forwarding_node)     + " " +
           to_string(e.stats.leader_node)         + " " +
           to_string(e.stats.time_leader_received) + " " +
           to_string(e.log_index)                 + " " +
           to_string(e.term)                      + " " +
           to_string(e.checksum)                  + "\n";
}

// commit
void apply_entry(const string& k, const string& v) {

    entry e;
    e.wr.k = k;
    e.wr.v = v;
    e.stats.forwarding_node = node_id;
    e.stats.time_leader_received = now_ms();

    // wait for lock
    {
        unique_lock x(db_mutex);

        // set order
        e.log_index = log_index.fetch_add(1);
        e.checksum  = compute_checksum(e);

        string str_entry = serialize_entry(e);

        // flush to wal in same order
        {

            // guards from truncate_wal
            lock_guard y(wal_mutex);

            wal << str_entry;
            wal.flush();
        }

        db[e.wr.k] = e.wr.v;
    }

    {
        lock_guard z(dk_mutex);
        dk.insert(e.wr.k);
    }

}
string apply_r(const string& k) {
    shared_lock lock(db_mutex);
    auto it = db.find(k);
    return it != db.end() ? it->second : "KEY_NOT_FOUND";
}

// wal snap stuff
void ensure_walsnap_open() {
    create_directories(SNAP_DIR_PATH);
    wal.open(WAL_PATH, ios::app);
    if (!wal.is_open())
        throw runtime_error("[main] could not setup write handler");
}
void remove_temp_snap() {
    for (auto& entry : directory_iterator(SNAP_DIR_PATH))
        if (entry.path().extension() == ".tmp") remove(entry.path());
    if (exists(WAL_PATH + ".tmp")) remove(WAL_PATH + ".tmp");
}
void truncate_wal(int idx_during_snap) {
    lock_guard lock(wal_mutex);
    ifstream old_wal(WAL_PATH);
    ofstream new_wal(WAL_PATH + string(".tmp"));

    string line;
    while (getline(old_wal, line)) {
        if (line.empty()) continue;
        istringstream ss(line);
        string k, v;
        int fn, ln, tlr, idx, term, cs;
        ss >> k >> v >> fn >> ln >> tlr >> idx >> term >> cs;

        if (ss.fail()) continue;

        if (idx >= idx_during_snap)
            new_wal << line << "\n";
    }
    new_wal.flush(); new_wal.close(); old_wal.close();

    rename((WAL_PATH + string(".tmp")).c_str(), WAL_PATH.c_str());
    wal.close(); wal.open(WAL_PATH, ios::app);
}

/*
A snapshot captures the DB state at a log index called the snap index
Holding the DB lock while dumping the DB into a snapshot prevents capturing a partial state
log index increments within the db lock.
Meaning, the log index can't advance during the dump.
Therefore, snapshot is taken when we grab the DB lock

key is dirty if it was updated after snapshot
if we take the snapshot after another thread updates the DB but before
the thread can mark a key dirty, then a fresh key is incorrectly marked dirty.
This results in unnecessarily replaying an entry when constructing the next snap
This is not a correctness issue, with negligible performance impact
The fix is a bit complex, so I will just document this as a tradeoff
*/
void take_pics() {
    int prev_snap_idx = 0;
    while (true) {
        if (log_index.load() - prev_snap_idx < 100) continue;

        str_arr_1D empty;
        {
            lock_guard lock(dk_mutex);
            swap(empty, dk);
        }
        str_arr_1D dk = empty;

        str_arr_2D wip_snap_arr = prev_snap_arr;
        int snap_idx;
        {
            shared_lock lock(db_mutex);
            snap_idx = log_index.load();
            for (auto& k : dk)
                wip_snap_arr[k] = db.contains(k) ? db.at(k) : "";
        }
        str_arr_2D new_snap_arr = wip_snap_arr;

        // snap.tmp --> snap.txt
        ofstream f(SNAP_DIR_PATH + "snap" + ".tmp");
        f << snap_idx << "\n";
        for (auto& [k, v] : new_snap_arr) f << k << " " << v << "\n";
        f.flush(); f.close();
        rename((SNAP_DIR_PATH + "snap" + ".tmp").c_str(), (SNAP_DIR_PATH + "snap").c_str());

        truncate_wal(snap_idx);
        prev_snap_arr = std::move(new_snap_arr);
        prev_snap_idx = snap_idx;
        sleep_for(seconds(3));
    }
}
int load_snap() {
    ifstream f(SNAP_DIR_PATH + "snap");

    if (!f.is_open()) {
        cerr << "[load_snap] No prev snap found — expected only on fresh deploy\n";
        return 0;
    }

    string line;
    getline(f, line);
    int snap_idx = stoi(line);

    while (getline(f, line)) {
        auto sp = line.find(' ');
        if (sp == string::npos) continue;
        string k = line.substr(0, sp);
        string v = line.substr(sp + 1);
        db[k] = v;
        prev_snap_arr[k] = v;
    }

    return snap_idx;
}
void replay_wal(int idx_dur_snap) {

    ifstream f(WAL_PATH);

    if (!f.is_open())
        throw runtime_error("[replay_wal] could not open WAL content\n");

    // handles case where idx_during_latest_snap is last write in WAL
    int idx_of_last_wr_in_wal = idx_dur_snap;

    string line;
    while (getline(f, line)) {
        if (line.empty()) continue;

        istringstream ss(line);
        string k, v;
        int fn, ln, tlr, idx, term, cs;
        ss >> k >> v >> fn >> ln >> tlr >> idx >> term >> cs;

        if (ss.fail()) continue; // partial
        if (idx < idx_dur_snap) continue; // covered by snap

        entry e;
        e.wr.k = k;
        e.wr.v = v;
        e.stats.forwarding_node = fn;
        e.stats.leader_node = ln;
        e.stats.time_leader_received = tlr;
        e.log_index = idx;
        e.term = term;
        e.checksum = compute_checksum(e);

        // partial
        if (e.checksum != cs) continue;

        // prev_snap = db on boot
        db[e.wr.k] = e.wr.v;
        prev_snap_arr[e.wr.k] = e.wr.v;

        idx_of_last_wr_in_wal = idx;
    }
    log_index.store(idx_of_last_wr_in_wal);
}