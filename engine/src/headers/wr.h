#pragma once
#include <string>
#include <cstdint>

struct wr {
    std::string k;
    std::string v;
    uint8_t  forwarding_node{0};
    uint8_t  leader_node{0};
    uint64_t time_leader_received{0};
    uint32_t log_index{0}; // prior writes to leader
    uint32_t term{0};
    uint32_t checksum{0};
};

uint32_t compute_checksum(const wr& w);
std::string serialize_wr(const wr& w);
