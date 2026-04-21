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

    static wr make_new_wr(const std::string& k, const std::string& v, uint8_t src, uint32_t seq);
};

uint32_t get_checksum(const wr& w);
std::string serialize_wr(const wr& w);
wr make_foreign_wr(const std::string& k, const std::string& v, uint8_t src, uint32_t seq, uint64_t t);