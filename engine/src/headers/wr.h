#pragma once
#include <string>
#include <cstdint>

uint64_t now_ms();

struct wr {
    std::string  k;
    std::string  v;
    uint64_t     t{0};
    uint8_t      src{0};
    uint32_t     i{0};
    uint32_t     checksum{0};
};

uint32_t compute_checksum(const wr& w);
std::string serialize_wr(const wr& w);
