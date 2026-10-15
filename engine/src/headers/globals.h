#pragma once
#include <string>
#include <atomic>
#include <shared_mutex>
#include <unordered_map>
#include <fstream>
#include <random>
#include <unordered_set>
#include <thread>
#include <chrono>
#include <filesystem>
#include <vector>
#include <optional>

// namespaces
using namespace std;
using namespace std::chrono;
using namespace this_thread;
using namespace filesystem;

// types
using str_arr_1D = unordered_set<string>;
using str_arr_2D = unordered_map<string, string>;
using xnt = uint32_t;

struct write_cmd {
    string k;
    string v;
};
struct raft_stats {
    int  forwarding_node{0};
    int  leader_node{0};
    int time_leader_received{0};
};
struct entry {
    write_cmd wr;
    raft_stats stats;

    xnt log_index{0};
    xnt term{0};
    xnt checksum{0};
};

// enums
enum Op {
    WRITE          = 1,
    READ           = 2,
    REQUEST_VOTE   = 3,
    APPEND_ENTRIES = 4,
    HELLO          = 5,
};
enum Status : uint8_t {
    I_AM_LEADER     = 11,
    I_AM_NOT_LEADER = 12,
    IDK             = 13,
};

// sentinels
inline constexpr int NO_LEADER = -1;
inline constexpr int NO_VOTE   = -1;

// global variables
extern int myNodeID;
extern std::atomic<xnt> log_index;
inline constexpr int NUM_NODES = 5;
extern std::vector<std::atomic<int>> my_fd_to;
extern std::atomic<int> relay_fd;

// utils
inline xnt now_ms() {
    return std::chrono::duration_cast<milliseconds>(
        system_clock::now().time_since_epoch()
    ).count();
}
inline xnt compute_checksum(const entry& e) {
    xnt crc = 0xFFFFFFFF;
    string data = e.wr.k                                    +
                  e.wr.v                                    +
                  to_string(e.stats.forwarding_node)        +
                  to_string(e.stats.leader_node)            +
                  to_string(e.stats.time_leader_received)   +
                  to_string(e.log_index)                    +
                  to_string(e.term);
    for (char c : data) {
        crc ^= static_cast<xnt>(c);
        for (int j = 0; j < 8; j++)
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return crc ^ 0xFFFFFFFF;
}
inline int rand_sleep_timer_ms(int lo, int hi) {
    static thread_local mt19937 rng(std::random_device{}());
    uniform_int_distribution<int> dist(lo, hi);
    return dist(rng);
}

//  *   *   * shared methods *  *   *

//snap
void truncate_wal(xnt idx_during_snap);

// raft
xnt get_log_length();
xnt get_last_log_term();
xnt get_cur_term();

// network
bool send_to_peer(int peer, const string& buf);
