#include "headers/db.h"
#include "headers/wr.h"
#include "headers/globals.h"
#include <fstream>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <unordered_set>
#include <chrono>
#include <filesystem>
#include <sstream>

using namespace std;

static const uint32_t WRITES_BETWEEN_SNAPS = 100;
static const string SNAP_DIR = "/var/log/ameyaDB/";

static unordered_map<string,string> old_snap;
static unordered_set<string> dirty_keys;
static mutex dirty_keys_mutex;

uint32_t compute_checksum(const wr& w) {
    uint32_t crc = 0xFFFFFFFF;
    string data = to_string(w.time_leader_received)   +
                  to_string(w.forwarding_node) +
                  to_string(w.log_index)   +
                  w.k               +
                  w.v;
    for (char c : data) {
        crc ^= static_cast<uint8_t>(c);
        for (int j = 0; j < 8; j++)
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return crc ^ 0xFFFFFFFF;
}
string serialize_wr(const wr& w) {
    return to_string(w.time_leader_received)        + " " +
           to_string(w.forwarding_node)      + " " +
           to_string(w.log_index)        + " " +
           w.k                   + " " +
           w.v                   + " " +
           to_string(w.checksum) + "\n";
}

void apply_wr(const wr& w) {

    string str_wr = serialize_wr(w);

    // write to WAL
    {
        lock_guard lock(wal_mutex);
        wal << str_wr;
        wal.flush();
    }

    // write to DB
    {
        unique_lock lock(db_mutex);
        db[w.k] = w.v;
    }

    // write to dirty keys
    {
        lock_guard lock(dirty_keys_mutex);
        dirty_keys.insert(w.k);
    }

}
string apply_r(const string& k) {
    shared_lock lock(db_mutex);
    auto it = db.find(k);
    return it != db.end() ? it->second : "";
}

void take_pictures() {

    uint32_t writes_since_last_pic = 0;
    while (true) {

        this_thread::sleep_for(chrono::seconds(5));
        uint32_t seqX = writes_received.load();

        if (seqX - writes_since_last_pic < WRITES_BETWEEN_SNAPS)
            continue;

        // swap dirty keys
        unordered_set<string> new_dirty_keys;
        {
            lock_guard lock(dirty_keys_mutex);
            swap(new_dirty_keys, dirty_keys);
        }

        // build new snapshot
        unordered_map<string,string> new_snap = old_snap;
        {
            shared_lock lock(db_mutex);
            for (auto& k : new_dirty_keys)
                new_snap[k] = db.count(k) ? db.at(k) : "";
        }

        // write to disk
        ofstream f(SNAP_DIR + "snapshot." + to_string(seqX) + ".bin");
        for (auto& [k, v] : new_snap)
            f << k << " " << v << "\n";
        f.flush();

        old_snap = move(new_snap);
        writes_since_last_pic = seqX;
    }
}
uint32_t load_snapshot() {
    uint32_t best_seq = 0;
    for (auto& entry : filesystem::directory_iterator(SNAP_DIR)) {
        string name = entry.path().filename().string();
        if (name.rfind("snapshot.", 0) == 0 && name.ends_with(".bin")) {
            uint32_t s = stoul(name.substr(9, name.size() - 13));
            if (s > best_seq) best_seq = s;
        }
    }

    if (best_seq == 0) return 0;

    ifstream f(SNAP_DIR + "snapshot." + to_string(best_seq) + ".bin");
    if (!f.is_open()) return 0;

    string line;
    unique_lock lock(db_mutex);
    while (getline(f, line)) {
        auto sp = line.find(' ');
        if (sp == string::npos) continue;
        string k = line.substr(0, sp);
        string v = line.substr(sp + 1);
        db[k] = v;
        old_snap[k] = v;
    }

    return best_seq;
}
void replay_wal(uint32_t after_seq) {
    ifstream f(SNAP_DIR + "wal.log");
    if (!f.is_open()) return;

    string line;
    while (getline(f, line)) {
        if (line.empty()) continue;

        istringstream ss(line);
        uint64_t time_leader_received;
        uint32_t forwarding_node, log_index, checksum;
        string k, v;
        ss >> time_leader_received >> forwarding_node >> log_index >> k >> v >> checksum;

        if (ss.fail())
            continue;

        // already covered by snapshot
        if (log_index <= after_seq)
            continue;

        wr w;
        w.k = k;
        w.v = v;
        w.time_leader_received = time_leader_received;
        w.forwarding_node = static_cast<uint8_t>(forwarding_node);
        w.log_index = log_index;
        w.checksum = compute_checksum(w);

        // skip corrupted entries
        if (w.checksum != checksum)
            continue;

        {
            unique_lock lock(db_mutex);
            db[w.k] = w.v;
        }
    }
}