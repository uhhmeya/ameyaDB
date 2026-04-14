#include <iostream>
#include <fstream>
#include <string>
#include <cstdint>
#include <chrono>

using namespace std;

#define NODE_ID 2

struct wr {
    string   k;
    string   v;
    uint64_t t;
    uint8_t  id;
    uint32_t i;
    uint32_t checksum;
};

uint64_t now_ms() {
    return chrono::duration_cast<chrono::milliseconds>(
        chrono::system_clock::now().time_since_epoch()
    ).count();
}

uint32_t get_checksum(const wr& w) {
    uint32_t crc = 0xFFFFFFFF;
    string data = to_string(w.t)  +
                  to_string(w.id) +
                  to_string(w.i)  +
                  w.k              +
                  w.v;
    for (char c : data) {
        crc ^= (uint8_t)c;
        for (int i = 0; i < 8; i++)
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return crc ^ 0xFFFFFFFF;
}

string serialize_wr(const wr& w) {
    return to_string(w.t)        + " " +
           to_string(w.id)       + " " +
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

int main() {
    cout << "node " << NODE_ID << " starting..." << endl;

    wr w;
    w.k  = "user:123";
    w.v  = "john";
    w.t  = now_ms();
    w.id = NODE_ID;
    w.i  = 1;
    w.checksum = get_checksum(w);

    append_wal(w);
    cout << serialize_wr(w);

    return 0;
}