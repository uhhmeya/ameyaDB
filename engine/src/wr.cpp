#include "headers/wr.h"
#include <chrono>
#include <string>

using namespace std;

uint64_t now_ms() {
    return chrono::duration_cast<chrono::milliseconds>(
        chrono::system_clock::now().time_since_epoch()
    ).count();
}
uint32_t get_checksum(const wr& w) {
    uint32_t crc = 0xFFFFFFFF;
    string data = to_string(w.t)   +
                  to_string(w.src) +
                  to_string(w.i)   +
                  w.k               +
                  w.v;
    for (char c : data) {
        crc ^= static_cast<uint8_t>(c);
        for (int j = 0; j < 8; j++)
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return crc ^ 0xFFFFFFFF;
}
string serialize_wr(const wr& w) {
    return to_string(w.t)        + " " +
           to_string(w.src)      + " " +
           to_string(w.i)        + " " +
           w.k                   + " " +
           w.v                   + " " +
           to_string(w.checksum) + "\n";
}

// from client
wr make_new_wr(const string& k, const string& v, uint8_t src, uint32_t seq) {
    wr w;
    w.k        = k;
    w.v        = v;
    w.t        = now_ms();
    w.src      = src;
    w.i        = seq;
    w.checksum = get_checksum(w);
    return w;
}

// from SQS
wr make_old_wr(const string& k, const string& v, uint8_t src, uint32_t seq, uint64_t t) {
    wr w;
    w.k        = k;
    w.v        = v;
    w.t        = t;
    w.src      = src;
    w.i        = seq;
    w.checksum = get_checksum(w);
    return w;
}