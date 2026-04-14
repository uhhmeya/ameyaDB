#include <iostream>
#include <fstream>
#include <string>
#include <cstdint>
#include <chrono>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <atomic>
#include <thread>

using namespace std;

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

void handle_client(int client_fd, int node_id, atomic<uint32_t>& seq) {
    uint32_t k_len;
    read(client_fd, &k_len, sizeof(k_len));
    string k(k_len, '\0');
    read(client_fd, &k[0], k_len);

    uint32_t v_len;
    read(client_fd, &v_len, sizeof(v_len));
    string v(v_len, '\0');
    read(client_fd, &v[0], v_len);

    wr w;
    w.k        = k;
    w.v        = v;
    w.t        = now_ms();
    w.id       = node_id;
    w.i        = ++seq;
    w.checksum = get_checksum(w);

    append_wal(w);

    uint8_t ack = 1;
    write(client_fd, &ack, sizeof(ack));
    close(client_fd);
}

void start_server(int node_id) {
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);

    sockaddr_in addr;
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port        = htons(8080);

    bind(server_fd, (sockaddr*)&addr, sizeof(addr));
    listen(server_fd, 10);

    cout << "node " << node_id << " listening on port 8080" << endl;

    atomic<uint32_t> seq(0);
    while (true) {
        int client_fd = accept(server_fd, nullptr, nullptr);
        thread(handle_client, client_fd, node_id, ref(seq)).detach();
    }
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        cerr << "usage: ./node <node_id>" << endl;
        return 1;
    }
    int node_id = atoi(argv[1]);
    cout << "node " << node_id << " starting..." << endl;
    start_server(node_id);
    return 0;
}