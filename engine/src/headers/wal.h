#pragma once
#include <string>
#include <cstdint>

struct wr {
    std::string   k;
    std::string   v;
    uint64_t t{0};
    uint8_t  src{0};
    uint32_t i{0};
    uint32_t checksum{0};
};

uint64_t now_ms();
uint32_t get_checksum(const wr& w);
std::string serialize_wr(const wr& w);
void append_wal(const wr& w);