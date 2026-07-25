#include <iostream>
#include <thread>
#include <shared_mutex>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <arpa/inet.h>

#include "../headers/globals.h"

int my_node_id;
atomic<uint32_t> log_index{0};

void handle_write(int x);

void handle_read(int x);

void ensure_wal_is_open();

void remove_temp_snap();

void take_pics();

uint32_t load_snap();

void replay_wal(uint32_t x);

int make_listener() {
    // makes listener
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);

    // make sure listener exists
    if (server_fd < 0)
        throw runtime_error("[make_listener] socket failed: " + string(strerror(errno)));

    // fix annoying OS behavior
    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    // claim port, then bind listener to port
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(LOCAL_ADDRS[my_node_id].port);
    if (::bind(server_fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0)
        throw runtime_error("[make_listener] bind failed: " + string(strerror(errno)));

    // turns listener on
    if (listen(server_fd, 10) < 0)
        throw runtime_error("[make_listener] listen failed: " + string(strerror(errno)));

    return server_fd;
}

int initiate(int peer_id) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(8080 + peer_id);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (connect(fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0) {
        cerr << "[initiate] failed to connect to node " << peer_id << "\n";
        close(fd);
        return -1;
    }
    return fd;
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

//TODO= does myNodeID need to be a global or can it just be passed in?
//TODO= the port this process is occupying should be a variable that is passed in
//TODO= make a separate network.cpp file
//TODO= FD returned by initiate_connection() is not being stored anywhere
//TODO= replace unnecessary local_ADDRs lookup variable in use

//! (k v) (fn ln tlr) (i t CRC)
int main(int argc, char *argv[]) {
    my_node_id = stoi(argv[1]);

    ensure_wal_is_open();
    remove_temp_snap();
    uint32_t idx_dur_snap = load_snap();
    cerr << "[main] loaded snap_idx from previous boot = " << idx_dur_snap << endl;
    truncate_wal(idx_dur_snap);
    replay_wal(idx_dur_snap);

    thread([]() {
        take_pics();
    }).detach();

    int server_fd = make_listener();

    if (my_node_id == 0) {
        initiate(1);
        initiate(2);
    }

    else if (my_node_id == 1)
        initiate(2);

    while (true) {
        int client_fd = accept(server_fd, nullptr, nullptr);

        thread([client_fd]() {
            dispatch(client_fd);
        }).detach();
    }
}
