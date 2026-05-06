#include <iostream>
#include <thread>
#include <unordered_map>
#include <mutex>
#include <vector>
#include <string>
#include <cassert>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include "headers/globals.h"

static const int PORT = 8080;
static const int NUM_THREADS = 30;
static const int WRITES_PER_THREAD = 10;

static int connect_to_db() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(PORT);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
    if (connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
      close(fd); return -1;}
    return fd;
}

static string send_r(const string& k) {
    int fd = connect_to_db();
    if (fd < 0) return "CONNECTION_FAILED";

    uint8_t op = READ;
    uint32_t k_len = k.size();
    write(fd, &op,      1);
    write(fd, &k_len,   4);
    write(fd, k.data(), k_len);

    uint32_t v_len = 0;
    read(fd, &v_len, 4);
    string v(v_len, '\0');
    if (v_len > 0) read(fd, &v[0], v_len);
    close(fd);
    return v;
}

static void send_wr(int num_writes) {
    int fd = connect_to_db();
    if (fd < 0) throw runtime_error("failed to connect to DB");

    // send all writes concurrently
    for (int i = 0; i < num_writes; i++) {
        uint8_t op = WRITE;
        string k = "k" + to_string(rand() % 10);
        string v = "v" + to_string(rand() % 1000);
        uint32_t k_len = k.size();
        uint32_t v_len = v.size();
        write(fd, &op,      1);
        write(fd, &k_len,   4);
        write(fd, k.data(), k_len);
        write(fd, &v_len,   4);
        write(fd, v.data(), v_len);
    }

    // set 10s timeout between ACKs
    struct timeval tv{.tv_sec = 10, .tv_usec = 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    // crash if any writes are not ACK'd
    for (int i = 0; i < num_writes; i++) {
        uint8_t ack = 0;
        if (read(fd, &ack, 1) != 1)
            throw runtime_error("timed out waiting for ack");
    }

    close(fd);
}

int main() {
    vector<thread> clients;
    for (int i = 0; i < NUM_THREADS; i++)
        clients.emplace_back(send_wr, WRITES_PER_THREAD);
    for (auto& t : clients)
        t.join();
    return 0;
}

