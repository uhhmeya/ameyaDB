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

using namespace std;
using namespace std::chrono;
using namespace this_thread;
using namespace filesystem;

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

enum Op {
    WRITE          = 1,
    READ           = 2,
    HELLO          = 3,
    APPEND_ENTRIES = 4,
    VREQ           = 5,
    VRES           = 6,
    AERES          = 7,
    SNAP           = 8,
};
enum Status : uint8_t {
    I_AM_LEADER     = 11,
    I_AM_NOT_LEADER = 12,
    IDK             = 13,
};

inline constexpr int NO_LEADER = -1;
inline constexpr int NO_VOTE   = -1;
inline const string  NO_OP     = "~no_op~";

extern int myNodeID;
extern std::atomic<xnt> log_index;
inline constexpr int NUM_NODES = 5;
extern std::vector<std::atomic<int>> my_fd_to;
extern std::atomic<int> relay_fd;

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

void truncate_wal(xnt last_log_idx_in_snap, xnt last_term_in_snap);
xnt get_log_idx();
xnt get_last_log_term();
xnt get_cur_term();
bool Psend(int peer, const string& buf);
void get_log_idx_and_last_log_term(xnt &index, xnt &term);
xnt append_entry(const string& k, const string& v, xnt term);
void append_entries(const vector<entry>& suffix);
void apply_entries(xnt commit_idx);
bool log_ok(xnt last_log_idx_in_old_batch, xnt last_log_term_in_old_batch);
bool get_suffix(xnt &last_log_idx_in_old_batch, xnt &last_log_term_in_old_batch, vector<entry> &suffix);
xnt get_term(xnt idx);
xnt get_applied_idx();
xnt get_oldest_idx_a_follower_needs();
string read_snap();
xnt install_snap(const string& snap);
string log_stat();
string net_stat();
int get_flag(const string& name, int fallback);
void disk_stall();
