#include "headers/wal.h"
#include <fstream>
#include <sstream>
#include <chrono>

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
           w.k                    + " " +
           w.v                    + " " +
           to_string(w.checksum) + "\n";
}

void append_wal(const wr& w) {
    ofstream wal("/var/log/ameyaDB/wal.log", ios::app);
    wal << serialize_wr(w);
    wal.flush();
}