#pragma once
#include <string>
#include <atomic>
#include <shared_mutex>
#include <unordered_map>
#include <fstream>
#include <chrono>
#include <unordered_set>

struct wr {
    std::string k;
    std::string v;
    uint8_t  forwarding_node{0};
    uint8_t  leader_node{0};
    uint64_t time_leader_received{0};
    uint32_t log_index{0};
    uint32_t term{0};
    uint32_t checksum{0};
};

// namespaces
using namespace std;
using namespace std::chrono;
using namespace this_thread;
using namespace filesystem;

// types
using str_arr_1D = unordered_set<string>;
using str_arr_2D = unordered_map<string, string>;

// enums
enum Op {
    WRITE          = 1,
    READ           = 2,
    REQUEST_VOTE   = 3,
    APPEND_ENTRIES = 4,
};
enum Raft_Role {
    FOLLOWER,
    CANDIDATE,
    LEADER
};

// variables
extern int node_id;
extern std::atomic<uint32_t> log_index; // odr

// utils
inline uint64_t now_ms() {
    return std::chrono::duration_cast<milliseconds>(
        system_clock::now().time_since_epoch()
    ).count();
}
inline uint32_t compute_checksum(const wr& w) {
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

// shared
void truncate_wal(int idx_during_snap); // handlers + walsnap

// replay : walsnap


// AWS ---------------------------------------------------
inline const std::string SNS_TOPIC_ARN ="arn:aws:sns:us-east-1:540799520398:ameyaDB-replication";
inline const char* PEER_ADDRS[3] = {"node-0.ameyadb.internal","node-1.ameyadb.internal","node-2.ameyadb.internal",};
inline const std::string QUEUE_URLS[3] = {"https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-0","https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-1","https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-2"};