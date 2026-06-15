#include <iostream>
#include <thread>
#include <shared_mutex>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include "../headers/globals.h"

int node_id;
atomic<uint32_t> log_index{0};

void handle_write(int x);
void handle_read(int x);

void ensure_walsnap_open();
void remove_temp_snap();
void take_pics();
int load_snap();
void replay_wal(int x);

int make_listener() {
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0)
        throw runtime_error("[make_listener] socket failed: " + string(strerror(errno)));

    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port        = htons(8080);

    if (::bind(server_fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0)
        throw runtime_error("[make_listener] bind failed: " + string(strerror(errno)));

    if (listen(server_fd, 10) < 0)
        throw runtime_error("[make_listener] listen failed: " + string(strerror(errno)));
    return server_fd;
}

void dispatch(int client_fd) {
    char op = 0;
    while (read(client_fd, &op, 1) == 1) {
        if (op == WRITE)
            handle_write(client_fd);
        else if (op == READ)
            handle_read(client_fd);
    }
    close(client_fd);
}

int main(int argc, char* argv[]) {
    node_id = stoi(argv[1]);
    ensure_walsnap_open();
    remove_temp_snap();
    int idx_dur_snap = load_snap();
    truncate_wal(idx_dur_snap);
    replay_wal(idx_dur_snap);

    thread([]() {
        take_pics();
    }).detach();

    int server_fd = make_listener();
    while (true) {
        int client_fd = accept(server_fd, nullptr, nullptr);

        thread([client_fd]() {
            dispatch(client_fd);
        }).detach();
    }
}