#pragma once
#include <string>
#include <atomic>
#include <shared_mutex>
#include <unordered_map>

extern int node_id;
extern std::atomic<uint32_t> seq;
extern std::unordered_map<std::string, std::string> db;
extern std::shared_mutex db_mutex;
using namespace std;

const std::string SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:540799520398:ameyaDB-replication";
const std::string QUEUE_URLS[3] = {
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-0",
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-1",
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-2"
};