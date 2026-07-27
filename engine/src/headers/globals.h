#pragma once
#include <string>
#include <atomic>
#include <shared_mutex>
#include <unordered_map>
#include <fstream>
#include <chrono>
#include <unordered_set>

// namespaces
using namespace std;
using namespace std::chrono;
using namespace this_thread;
using namespace filesystem;

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

// types
using str_arr_1D = unordered_set<string>;
using str_arr_2D = unordered_map<string, string>;

// enums
enum Op {
    WRITE          = 1,
    READ           = 2,
    REQUEST_VOTE   = 3,
    APPEND_ENTRIES = 4,
    HELLO          = 5,
};


// we want to make this global
extern int myNodeID;
extern std::atomic<xnt> log_index;

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

// shared
void truncate_wal(xnt idx_during_snap);


// AWS
inline const std::string SNS_TOPIC_ARN ="arn:aws:sns:us-east-1:540799520398:ameyaDB-replication";
inline const char* PEER_ADDRS[3] = {"node-0.ameyadb.internal","node-1.ameyadb.internal","node-2.ameyadb.internal",};
inline const std::string QUEUE_URLS[3] = {"https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-0","https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-1","https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-2"};

