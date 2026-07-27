#include <iostream>
#include <thread>
#include <chrono>
#include <mutex>
#include <atomic>
#include <shared_mutex>
#include <sys/socket.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#include "../headers/globals.h"

int myNodeID;
atomic<xnt> log_index{0};

static atomic<int> my_fd_to_node0{-1};
static atomic<int> my_fd_to_node1{-1};
static atomic<int> my_fd_to_node2{-1};

void handle_write(int x);
void handle_read(int x);
void ensure_wal_is_open();
void remove_temp_snap();
void take_pics();
xnt load_snap();
void replay_wal(xnt x);


int attach_listener_to_port(int myPort) {
    int listener_fd = socket(AF_INET, SOCK_STREAM, 0);

    if (listener_fd < 0)
        throw runtime_error("[attach_listener_to_port] socket failed: " + string(strerror(errno)));

    int opt = 1;
    setsockopt(listener_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(myPort);
    if (::bind(listener_fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0)
        throw runtime_error("[attach_listener_to_port] bind failed: " + string(strerror(errno)));

    if (listen(listener_fd, 10) < 0)
        throw runtime_error("[attach_listener_to_port] listen failed: " + string(strerror(errno)));

    return listener_fd;
}

static int initiate(int peer_id) {
    int attempts = 200;
    int backoff_ms = 100;
    int peerPort = 8080 + peer_id;

    for (int i = 0; i < attempts; ++i) {

        // a socket that failed connect() is unusable -- make a fresh one each try
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0)
            throw runtime_error("[initiate] socket failed: " + string(strerror(errno)));

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(peerPort);
        inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

        // TCP connection is established here
        if (connect(fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0) {
            close(fd);
            sleep_for(milliseconds(backoff_ms));
            continue;
        }

        // initiator sends his nodeID
        char msg[2] = { HELLO, static_cast<char>(myNodeID) };
        if (write(fd, msg, 2) != 2) {
            close(fd);
            throw runtime_error("[initiate] failed to send hello to node " + to_string(peer_id));
        }

        return fd;
    }

    throw runtime_error("[initiate] no listener came up on port " + to_string(peerPort));
}

// identifies initiators nodeID
void handle_hello(int client_fd) {

    char sender_id = 0;
    if (read(client_fd, &sender_id, 1) != 1) {
        close(client_fd);
        return;
    }

    if (sender_id == 0)
        my_fd_to_node0 = client_fd;

    else if (sender_id == 1)
        my_fd_to_node1 = client_fd;

    else if (sender_id == 2)
        my_fd_to_node2 = client_fd;
}

void print_my_fds() {
    cout << "[node " << myNodeID << "]"
         << " fd_to_node0=" << my_fd_to_node0.load()
         << " fd_to_node1=" << my_fd_to_node1.load()
         << " fd_to_node2=" << my_fd_to_node2.load()
         << endl;
}

void dispatch(int client_fd) {
    char op = 0;
    while (read(client_fd, &op, 1) == 1) {

        if (op == WRITE)
            handle_write(client_fd);

        else if (op == READ)
            handle_read(client_fd);

        else if (op == HELLO)
            handle_hello(client_fd);
    }
    close(client_fd);
}

//! (k v) (fn ln tlr) (i t CRC)
int main(int argc, char *argv[]) {

    if (argc < 2)
        throw runtime_error("[main] usage: server <nodeID>");

    myNodeID = stoi(argv[1]);
    int myPort = 8080 + myNodeID;

    ensure_wal_is_open();
    remove_temp_snap();
    xnt snap_idx = load_snap();
    truncate_wal(snap_idx);
    replay_wal(snap_idx);

    thread([]() {
        take_pics();
    }).detach();

    int listenerFD = attach_listener_to_port(myPort);

    // fd monitor -- started before the initiates so the retry phase is visible
    thread([]() {
        while (true) {
            print_my_fds();
            sleep_for(milliseconds(500));
        }
    }).detach();

    if (myNodeID == 0) {
        my_fd_to_node1 = initiate(1);
        my_fd_to_node2 = initiate(2);
    }

    if (myNodeID == 1) {
        my_fd_to_node2 = initiate(2);
    }

    while (true) {

        // node0 never accepts connections
        if (myNodeID == 0) {
            sleep_for(hours(24));
            continue;
        }

        int peerFD = accept(listenerFD, nullptr, nullptr);
        if (peerFD < 0) continue;
        thread([peerFD]() {
            dispatch(peerFD);
        }).detach();
    }
}