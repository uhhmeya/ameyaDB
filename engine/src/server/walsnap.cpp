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
#include <algorithm>
#include <iterator>

static const string SNAP_DIR_PATH = "../output/snaps/";
static const string WAL_PATH      = "../output/wal.txt";

static unordered_map<string, string> db;
static shared_mutex db_mutex;
static ofstream wal;
static mutex log_mutex;
static mutex snap_mutex;
static str_arr_2D prev_snap_arr;
static str_arr_1D dk;
static vector<entry> log_vector;
static xnt snap_index = 0;
static xnt snap_term  = 0;
static xnt applied_idx = 0;

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

static xnt term_at(xnt idx) {
    if (idx == snap_index) return snap_term;
    if (idx < snap_index || idx > snap_index + log_vector.size()) return 0;
    return log_vector[idx - snap_index - 1].term;
}

static void chop_wal(xnt idx) {
    log_vector.resize(idx - snap_index);

    ofstream new_wal(WAL_PATH + string(".tmp"));
    for (auto& e : log_vector) new_wal << serialize_entry(e);
    new_wal.flush(); new_wal.close();

    rename((WAL_PATH + string(".tmp")).c_str(), WAL_PATH.c_str());
    wal.close(); wal.open(WAL_PATH, ios::app);
}

// commit
void apply_entries(xnt commit_idx) {
    unique_lock x(db_mutex);
    lock_guard y(log_mutex);

    for (; applied_idx < commit_idx; applied_idx++) {
        const entry& e = log_vector[applied_idx - snap_index];
        db[e.wr.k] = e.wr.v;
        dk.insert(e.wr.k);
    }
}

xnt append_entry(const string& k, const string& v, xnt term) {

    entry e;
    e.wr.k = k;
    e.wr.v = v;
    e.term = term;
    e.stats.forwarding_node = myNodeID;
    e.stats.leader_node = myNodeID;
    e.stats.time_leader_received = now_ms();

    // guards from truncate_wal
    {
        lock_guard y(log_mutex);

        e.log_index = ++log_index;
        e.checksum  = compute_checksum(e);

        wal << serialize_entry(e);
        wal.flush();
        log_vector.push_back(e);
    }

    return e.log_index;
}

void append_entries(const vector<entry>& suffix) {
    lock_guard y(log_mutex);

    for (const entry& e : suffix) {
        xnt log_len = snap_index + log_vector.size();

        if (e.log_index <= snap_index) continue;
        if (e.log_index <= log_len && term_at(e.log_index) == e.term) continue;
        if (e.log_index > log_len + 1) break;
        if (e.log_index <= log_len) chop_wal(e.log_index - 1);

        wal << serialize_entry(e);
        log_vector.push_back(e);
    }
    wal.flush();

    log_index = snap_index + log_vector.size();
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

void truncate_wal(xnt snap_idx, xnt last_term) {
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
    snap_index = snap_idx;
    snap_term  = last_term;
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

        unique_lock s(snap_mutex);
        str_arr_1D empty;
        str_arr_2D wip_snap_arr = prev_snap_arr;
        xnt snap_idx, last_term;
        {
            shared_lock lock(db_mutex);
            swap(empty, dk);
            str_arr_1D local_dk = empty;
            {
                lock_guard l(log_mutex);
                snap_idx  = applied_idx;
                last_term = term_at(applied_idx);
            }
            for (auto& k : local_dk)
                wip_snap_arr[k] = db.contains(k) ? db.at(k) : "";
        }
        str_arr_2D new_snap_arr = wip_snap_arr;

        // snap.tmp --> snap.txt
        ofstream f(SNAP_DIR_PATH + "snap" + ".tmp");
        f << snap_idx << " " << last_term << "\n";
        for (auto& [k, v] : new_snap_arr) f << k << " " << v << "\n";
        f.flush(); f.close();
        rename((SNAP_DIR_PATH + "snap" + ".tmp").c_str(), (SNAP_DIR_PATH + "snap").c_str());

        truncate_wal(snap_idx, last_term);
        prev_snap_arr = std::move(new_snap_arr);
        prev_snap_idx = snap_idx;
        s.unlock();

        // prevent instant snapping
        sleep_for(milliseconds(rand_sleep_timer_ms(1200, 1800)));

    }
}

// load snap into DB
pair<xnt, xnt> load_snap() {
    ifstream f(SNAP_DIR_PATH + "snap");

    if (!f.is_open()) return {0, 0};

    string line;
    getline(f, line);
    istringstream hdr(line);
    xnt snap_idx = 0, last_term = 0;
    hdr >> snap_idx >> last_term;
    snap_index = snap_idx;
    snap_term  = last_term;
    applied_idx = snap_idx;

    while (getline(f, line)) {
        auto sp = line.find(' ');
        if (sp == string::npos) continue;
        string k = line.substr(0, sp);
        string v = line.substr(sp + 1);
        db[k] = v;
        prev_snap_arr[k] = v;
    }

    return {snap_idx, last_term};
}

// replay wal entry not covered by snap
void replay_wal(xnt snap_idx) {

    ifstream f(WAL_PATH);

    if (!f.is_open())
        throw runtime_error("[replay_wal] could not open WAL content\n");

    xnt highest_idx = snap_idx;

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
        if (idx != highest_idx + 1) break;

        log_vector.push_back(e);

        highest_idx = idx;
    }
    log_index.store(highest_idx);
}

// get last log entry
optional<entry> get_last_log_entry() {
    lock_guard lock(log_mutex);
    if (log_vector.empty()) return nullopt;
    return log_vector.back();
}

xnt get_log_idx() {
    lock_guard lock(log_mutex);
    return snap_index + static_cast<xnt>(log_vector.size());
}

xnt get_last_log_term() {
    lock_guard lock(log_mutex);
    return log_vector.empty() ? snap_term : log_vector.back().term;
}

void get_log_idx_and_last_log_term(xnt &index, xnt &term) {
    lock_guard g(log_mutex);
    if (!log_vector.empty()) {
        index = log_vector.back().log_index;
        term  = log_vector.back().term;
    } else {
        index = snap_index;
        term  = snap_term;
    }
}

bool log_ok(xnt last_log_idx_in_old_batch, xnt last_log_term_in_old_batch) {
    lock_guard lock(log_mutex);
    xnt my_log_idx = snap_index + log_vector.size();
    if (my_log_idx < last_log_idx_in_old_batch) return false;
    return last_log_idx_in_old_batch <= snap_index || term_at(last_log_idx_in_old_batch) == last_log_term_in_old_batch;
}


bool get_suffix(xnt &last_log_idx_in_old_batch, xnt &last_log_term_in_old_batch, vector<entry> &suffix) {
    lock_guard lock(log_mutex);

    bool suffix_starts_in_snap = last_log_idx_in_old_batch < snap_index;
    if (suffix_starts_in_snap) {
        last_log_idx_in_old_batch  = snap_index;
        last_log_term_in_old_batch = snap_term;
        return false;
    }

    last_log_term_in_old_batch = term_at(last_log_idx_in_old_batch);

    xnt first_pos = last_log_idx_in_old_batch - snap_index;
    for (xnt pos = first_pos; pos < log_vector.size() && suffix.size() < 1000; pos++)
        suffix.push_back(log_vector[pos]);

    return true;
}

xnt get_term(xnt idx) {
    lock_guard lock(log_mutex);
    return term_at(idx);
}

xnt get_applied_idx() {
    shared_lock lock(db_mutex);
    return applied_idx;
}

string read_snap() {
    ifstream f(SNAP_DIR_PATH + "snap");
    return string(istreambuf_iterator<char>(f), istreambuf_iterator<char>());
}

xnt install_snap(const string& snap) {
    lock_guard s(snap_mutex);

    istringstream f(snap);
    string line;
    getline(f, line);
    istringstream hdr(line);
    xnt snap_idx = 0, last_term = 0;
    hdr >> snap_idx >> last_term;

    if (snap_idx <= applied_idx) return applied_idx;

    str_arr_2D snap_arr;
    while (getline(f, line)) {
        auto sp = line.find(' ');
        if (sp == string::npos) continue;
        snap_arr[line.substr(0, sp)] = line.substr(sp + 1);
    }

    {
        lock_guard lock(log_mutex);
        if (snap_index + log_vector.size() > snap_idx && term_at(snap_idx) != last_term)
            chop_wal(snap_idx);
    }

    ofstream tmp(SNAP_DIR_PATH + "snap" + ".tmp");
    tmp << snap;
    tmp.flush(); tmp.close();
    rename((SNAP_DIR_PATH + "snap" + ".tmp").c_str(), (SNAP_DIR_PATH + "snap").c_str());

    truncate_wal(snap_idx, last_term);

    unique_lock x(db_mutex);
    lock_guard y(log_mutex);
    db = snap_arr;
    prev_snap_arr = std::move(snap_arr);
    dk.clear();
    applied_idx = snap_idx;
    log_index = snap_index + log_vector.size();

    return snap_idx;
}

string db_state() {
    shared_lock lock(db_mutex);

    xnt last_term;
    {
        lock_guard l(log_mutex);
        last_term = term_at(applied_idx);
    }

    unsigned long long digest = 0;
    for (auto& [k, v] : db) {
        entry e;
        e.wr.k = k;
        e.wr.v = v;
        digest += compute_checksum(e);
    }

    return to_string(applied_idx) + " " + to_string(last_term) + " " + to_string(db.size()) + " " + to_string(digest);
}


