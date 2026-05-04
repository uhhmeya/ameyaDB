#include "headers/db.h"
#include "headers/wr.h"
#include "headers/globals.h"
#include <fstream>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <unordered_set>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <cstdio>


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
    int idx_of_first_wr_in_prev_pic = 0;
    while (true) {
        sleep_for(seconds(5));
        int idx_of_first_wr_in_cur_pic = log_index.load();

        if (idx_of_first_wr_in_cur_pic - idx_of_first_wr_in_prev_pic < 100)
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

        string snap_name = "snapshot." + to_string(idx_of_first_wr_in_cur_pic);

        ofstream f(SNAP_DIR_PATH + snap_name + ".tmp");

        // write to snap.203.tmp
        for (auto& [k, v] : new_snap)
            f << k << " " << v << "\n";

        f.flush(); // flush remaining writes to snap.203.tmp
        f.close();

        // publish snap.203.bin via atomic rename
        rename((SNAP_DIR_PATH + snap_name + ".tmp").c_str(), (SNAP_DIR_PATH + snap_name + ".bin").c_str());

        {
            lock_guard lock(wal_mutex);

            ifstream old_wal(WAL_PATH); // wal.log
            ofstream new_wal(WAL_PATH + string(".tmp")); // wal.log.tmp

            // read from old wal
            string line;
            while (getline(old_wal, line)) {
                if (line.empty()) continue;
                istringstream ss(line);
                uint64_t t; uint32_t fn, idx, cs; string k, v;
                ss >> t >> fn >> idx >> k >> v >> cs;

                // put write in new wal if its either in the published snap or after it
                if (!ss.fail() && idx > idx_of_first_wr_in_cur_pic)
                    new_wal << line << "\n";
            }

            new_wal.flush();
            new_wal.close();
            old_wal.close();

            // publish truncated wal via atomic rename
            rename((WAL_PATH + string(".tmp")).c_str(), WAL_PATH.c_str());

            wal.close();
            wal.open(WAL_PATH, ios::app);
        }

        // increment
        prev_snap = move(new_snap);
        idx_of_first_wr_in_prev_pic = idx_of_first_wr_in_cur_pic;

        // delete old snaps
        for (auto& entry : directory_iterator(SNAP_DIR_PATH)) {
            string name = entry.path().filename().string();
            if (name.rfind("snapshot.", 0) == 0 && name.ends_with(".bin")) {
                uint32_t s = stoul(name.substr(9, name.size() - 13));
                if (s < idx_of_first_wr_in_cur_pic)  // older than the one we just wrote
                    remove(entry.path());
            }
        }
    }
}

int load_snap() {
    int log_idx_of_last_WR_in_latest_snap = 0;

    // find latest snap
    for (auto& entry : directory_iterator(SNAP_DIR_PATH)) {
        string name = entry.path().filename().string();
        if (name.rfind("snapshot.", 0) == 0 && name.ends_with(".bin")) {
            uint32_t s = stoul(name.substr(9, name.size() - 13));
            if (s > log_idx_of_last_WR_in_latest_snap)
                log_idx_of_last_WR_in_latest_snap = s;
        }
    }

    if (log_idx_of_last_WR_in_latest_snap == 0) {
        cerr << "[load_snap] No prev snap found — expected only on fresh deploy\n";
        return 0;
    }

    string latest_snap_path = SNAP_DIR_PATH + "snapshot." +
        to_string(log_idx_of_last_WR_in_latest_snap) + ".bin";

    ifstream f(latest_snap_path);

    // necessary because getLine fails silently
    if (!f.is_open())
        throw runtime_error("[load_snap] Could not open snapshot: " + latest_snap_path);

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

    return log_idx_of_last_WR_in_latest_snap;
}

void replay_wal(int log_idx_of_last_WR_in_latest_snap) {

    // open WAL content
    ifstream f(WAL_PATH);

    if (!f.is_open())
        throw runtime_error("[replay_wal] could not open WAL content\n");

    // handles case where snap covers all writes in WAL
    int max_log_idx = log_idx_of_last_WR_in_latest_snap;

    string line;
    while (getline(f, line)) {
        if (line.empty()) continue;

        // extract write
        istringstream ss(line);
        uint64_t time_leader_received;
        uint32_t forwarding_node, idx_of_wr, checksum;
        string k, v;
        ss >> time_leader_received >> forwarding_node >> idx_of_wr >> k >> v >> checksum;

        // discard partial write
        if (ss.fail())
            continue;

        // discard write covered by snapshot
        if (idx_of_wr <= log_idx_of_last_WR_in_latest_snap)
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

        max_log_idx = idx_of_wr;
    }
    log_index.store(max_log_idx);
}