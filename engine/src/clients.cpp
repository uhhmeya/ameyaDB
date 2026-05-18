#include <iostream>
#include <thread>
#include <vector>
#include <string>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <chrono>
#include <random>
#include <__random/random_device.h>

#include "headers/globals.h"

using namespace std::chrono_literals;

static const int PORT = 8080;
static const int num_clients = 30;
static const int key_pool = 20;
static const int val_pool = 100;

static int connect_to_db() {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(PORT);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
    if (connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        cerr << "[client] connection failed\n";
        close(fd); return -1;
    }
    return fd;
}

static void send_wr() {
    thread_local mt19937 rng(random_device{}());
    uniform_int_distribution kdist(0, key_pool - 1);
    uniform_int_distribution vdist(0, val_pool - 1);

    int fd = connect_to_db();
    if (fd < 0) throw runtime_error("failed to connect to DB");

    while (true) {
        uint8_t  op    = WRITE;
        string   k     = "k" + to_string(kdist(rng));
        string   v     = "v" + to_string(vdist(rng));
        uint32_t k_len = k.size();
        uint32_t v_len = v.size();
        write(fd, &op,      1);
        write(fd, &k_len,   4);
        write(fd, k.data(), k_len);
        write(fd, &v_len,   4);
        write(fd, v.data(), v_len);
    }
}

int main() {
    vector<thread> clients;
    for (int i = 0; i < num_clients; i++)
        clients.emplace_back(send_wr);
    for (auto& t : clients)
        t.join();
    return 0;
}