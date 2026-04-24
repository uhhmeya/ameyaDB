#pragma once
#include <string>
#include <atomic>
#include <shared_mutex>
#include <unordered_map>
#include <fstream>
#include <mutex>

extern int node_id;
extern std::atomic<uint32_t> writes_received;

extern std::unordered_map<std::string, std::string> db;
extern std::ofstream wal;

extern std::mutex wal_mutex;
extern std::shared_mutex db_mutex;

inline const std::string SNS_TOPIC_ARN =
    "arn:aws:sns:us-east-1:540799520398:ameyaDB-replication";

inline const std::string QUEUE_URLS[3] = {
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-0",
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-1",
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-2"
};