#include "headers/db.h"
#include "headers/wr.h"
#include "headers/globals.h"
#include <fstream>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <unordered_set>
#include <filesystem>
#include <sstream>

static const string SNAP_DIR = "/var/log/ameyaDB/";

static str_arr_2D prev_snap;
static str_arr_1D dk;
static mutex dk_mutex;

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

    {
        lock_guard lock(wal_mutex);
        wal << str_wr;
        wal.flush();
    }

    {
        unique_lock lock(db_mutex);
        db[w.k] = w.v;
    }

    {
        lock_guard lock(dk_mutex);
        dk.insert(w.k);
    }

}

string apply_r(const string& k) {
    shared_lock lock(db_mutex);
    auto it = db.find(k);
    return it != db.end() ? it->second : "";
}

void take_pictures() {
    int idx_in_prev_pic = 0;
    while (true) {
        sleep_for(seconds(5));
        int idx_in_cur_pic = log_index.load();
        if (idx_in_cur_pic - idx_in_prev_pic < 100)
            continue;

        str_arr_1D empty;
        {
            lock_guard lock(dk_mutex);
            swap(empty, dk);
        }
        str_arr_1D dk = empty;


        str_arr_2D wip_snap = prev_snap;
        {
            shared_lock lock(db_mutex);
            for (auto& k : dk)
                wip_snap[k] = db.contains(k) ? db.at(k) : "";
        }
        str_arr_2D new_snap = wip_snap;

        ofstream f(SNAP_DIR + "snapshot." + to_string(idx_in_cur_pic) + ".bin");
        for (auto& [k, v] : new_snap)
            f << k << " " << v << "\n";
        f.flush();

        prev_snap = move(new_snap);
        idx_in_prev_pic = idx_in_cur_pic;
    }
}

int load_snap() {

    // finds most recent snap
    int latest_snapshot_idx = 0;
    for (auto& entry : filesystem::directory_iterator(SNAP_DIR)) {
        string name = entry.path().filename().string();
        if (name.rfind("snapshot.", 0) == 0 && name.ends_with(".bin")) {
            uint32_t s = stoul(name.substr(9, name.size() - 13));
            if (s > latest_snapshot_idx) latest_snapshot_idx = s;
        }
    }
    if (latest_snapshot_idx == 0) return 0;
    ifstream f(SNAP_DIR + "snapshot." + to_string(latest_snapshot_idx) + ".bin");
    if (!f.is_open()) return 0;

    // extracts write
    string line;
    unique_lock lock(db_mutex);
    while (getline(f, line)) {
        auto sp = line.find(' ');
        if (sp == string::npos) continue;
        string k = line.substr(0, sp);
        string v = line.substr(sp + 1);

        // writes to db & prev_snap
        db[k] = v;
        prev_snap[k] = v;
    }

    return latest_snapshot_idx;
}

void replay_wal(uint32_t latest_snapshot_idx) {

    // open wal
    ifstream f(SNAP_DIR + "wal.log");
    if (!f.is_open()) return;
    string line;
    while (getline(f, line)) {
        if (line.empty()) continue;

        // extract write
        istringstream ss(line);
        uint64_t time_leader_received;
        uint32_t forwarding_node, idx_of_wr, checksum;
        string k, v;
        ss >> time_leader_received >> forwarding_node >> idx_of_wr >> k >> v >> checksum;
        if (ss.fail()) continue;

        // discard write covered by snapshot
        if (idx_of_wr <= latest_snapshot_idx)
            continue;

        wr w;
        w.k = k;
        w.v = v;
        w.time_leader_received = time_leader_received;
        w.forwarding_node = static_cast<uint8_t>(forwarding_node);
        w.log_index = idx_of_wr;
        w.checksum = compute_checksum(w);

        // discard partial write
        if (w.checksum != checksum)
            continue;

        db[w.k] = w.v;
        prev_snap[w.k] = w.v;
    }
}