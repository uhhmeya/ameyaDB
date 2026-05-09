#pragma once
#include <string>
#include <atomic>
#include <shared_mutex>
#include <unordered_map>
#include <fstream>
#include <chrono>
#include <unordered_set>

using namespace std;
using namespace std::chrono;
using namespace this_thread;
using namespace filesystem;

using str_arr_1D = unordered_set<string>;
using str_arr_2D = unordered_map<string, string>;

extern const string SNAP_DIR_PATH;
extern const string WAL_PATH;

enum Op {
    WRITE          = 1,
    READ           = 2,
    REQUEST_VOTE   = 3,
    APPEND_ENTRIES = 4,
};

enum Role {
    FOLLOWER,
    CANDIDATE,
    LEADER
};

struct committed_wr {
    string   k;
    string   v;
    uint32_t log_index;
};

#ifdef local_test
inline const string GLOBAL_WAL_PATH = "server/global_wal.txt";
inline const string SENTINEL_PATH   = "server/ready_to_crash";
#endif

extern int node_id;
extern std::atomic<uint32_t> log_index;

extern std::unordered_map<std::string, std::string> db;
extern std::ofstream wal;

extern std::mutex wal_mutex;
extern std::shared_mutex db_mutex;

extern std::atomic<uint32_t> term;
extern std::atomic<int>      vote;    // -1 = none
extern std::atomic<Role>     role;

extern std::atomic<uint64_t> time_of_last_hb_received;

inline uint64_t now_ms() {
    return std::chrono::duration_cast<milliseconds>(
        system_clock::now().time_since_epoch()
    ).count();
}

inline const std::string SNS_TOPIC_ARN =
    "arn:aws:sns:us-east-1:540799520398:ameyaDB-replication";

inline const char* PEER_ADDRS[3] = {
    "node-0.ameyadb.internal",
    "node-1.ameyadb.internal",
    "node-2.ameyadb.internal",
};

inline const std::string QUEUE_URLS[3] = {
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-0",
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-1",
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-2"
};