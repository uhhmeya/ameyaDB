#include "../headers/globals.h"
#include "../headers/threads.h"

#include <fstream>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <unordered_set>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <cstdio>
#include <random>
#include <algorithm>   // std::find_if -- GCC 10's <ranges> lacks the range algorithms

static const string SNAP_DIR_PATH = "../output/snaps/";
static const string WAL_PATH      = "../output/wal.txt";

static unordered_map<string, string> db;
static shared_mutex db_mutex;
static ofstream wal;
static mutex log_mutex;
static str_arr_2D prev_snap_arr;
static str_arr_1D dk;
static vector<entry> log_vector;
static xnt log_base = 0;

// turns entry into string
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
    e.stats.forwarding_node = myNodeID;
    e.stats.time_leader_received = now_ms();

    {
        unique_lock x(db_mutex);

        e.log_index = ++log_index;
        e.checksum  = compute_checksum(e);

        string str_entry = serialize_entry(e);

        // guards from truncate_wal
        {
            lock_guard y(log_mutex);

            wal << str_entry;
            wal.flush();
            log_vector.push_back(e);
        }
        db[e.wr.k] = e.wr.v;
        dk.insert(e.wr.k);
    }
}

// read
string apply_r(const string& k) {
    shared_lock lock(db_mutex);
    auto it = db.find(k);
    return it != db.end() ? it->second : "KEY_NOT_FOUND";
}

// ensure walsnap is open
void ensure_wal_is_open() {
    create_directories(SNAP_DIR_PATH);
    wal.open(WAL_PATH, ios::app);
    if (!wal.is_open())
        throw runtime_error("[main] could not setup write handler");
}

// remove temp snap on reboot
void remove_temp_snap() {
    for (auto& entry : directory_iterator(SNAP_DIR_PATH))
        if (entry.path().extension() == ".tmp") remove(entry.path());
    if (exists(WAL_PATH + ".tmp")) remove(WAL_PATH + ".tmp");
}

// truncate wal
void truncate_wal(xnt snap_idx) {
    lock_guard lock(log_mutex);
    ifstream old_wal(WAL_PATH);
    ofstream new_wal(WAL_PATH + string(".tmp"));

    string line;
    while (getline(old_wal, line)) {
        if (line.empty()) continue;
        istringstream ss(line);

        string k, v;
        int fn, ln;
        long long tlr;
        xnt idx, term, cs;
        ss >> k >> v >> fn >> ln >> tlr >> idx >> term >> cs;

        if (ss.fail()) continue;

        if (idx > snap_idx)
            new_wal << line << "\n";
    }
    new_wal.flush(); new_wal.close(); old_wal.close();

    rename((WAL_PATH + string(".tmp")).c_str(), WAL_PATH.c_str());
    wal.close(); wal.open(WAL_PATH, ios::app);

    auto cut = std::find_if(log_vector.begin(), log_vector.end(),
                            [&](const entry& e){ return e.log_index > snap_idx; });
    log_vector.erase(log_vector.begin(), cut);
    log_base = snap_idx;
}

// create snapshots
void take_pics() {
    xnt prev_snap_idx = 0;

    while (true) {

        // prevents constant checking when clients are not sending writes
        if (log_index.load() - prev_snap_idx < 100) {
            sleep_for(milliseconds(rand_sleep_timer_ms(100,700)));
            continue;
        }

        str_arr_1D empty;
        str_arr_2D wip_snap_arr = prev_snap_arr;
        xnt snap_idx;
        {
            shared_lock lock(db_mutex);
            swap(empty, dk);
            str_arr_1D local_dk = empty;
            snap_idx = log_index.load();
            for (auto& k : local_dk)
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

        // prevent instant snapping
        sleep_for(milliseconds(rand_sleep_timer_ms(1200, 1800)));

    }
}

// load snap into DB
xnt load_snap() {
    ifstream f(SNAP_DIR_PATH + "snap");

    if (!f.is_open()) return 0;

    string line;
    getline(f, line);
    xnt snap_idx = stoul(line);

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

// replay wal entry not covered by snap
void replay_wal(xnt snap_idx) {

    ifstream f(WAL_PATH);

    if (!f.is_open())
        throw runtime_error("[replay_wal] could not open WAL content\n");

    log_base = snap_idx;
    xnt highest_committed_idx = snap_idx;

    string line;
    while (getline(f, line)) {
        if (line.empty()) continue;

        istringstream ss(line);

        string k, v;
        int fn, ln;
        long long tlr;
        xnt idx, term, cs;
        ss >> k >> v >> fn >> ln >> tlr >> idx >> term >> cs;

        if (ss.fail()) continue; // partial
        if (idx <= snap_idx) continue; // covered by snap

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
        log_vector.push_back(e);

        highest_committed_idx = idx;
    }
    log_index.store(highest_committed_idx);
}

// get last log entry
optional<entry> get_last_log_entry() {
    lock_guard lock(log_mutex);
    if (log_vector.empty()) return nullopt;
    return log_vector.back();
}

xnt get_log_length() {
    lock_guard lock(log_mutex);
    return log_base + static_cast<xnt>(log_vector.size());
}

xnt get_last_log_term() {
    lock_guard lock(log_mutex);
    return log_vector.empty() ? 0 : log_vector.back().term;
}