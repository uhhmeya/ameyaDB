#include <iostream>
#include <thread>
#include <chrono>
#include <atomic>
#include <csignal>
#include <cstring>
#include <cerrno>
#include <sys/socket.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#include "../headers/globals.h"

int myNodeID;
atomic<xnt> log_index{0};

int NUM_NODES = 3;

static atomic<int> my_fd_to[NUM_NODES] = {-1, -1, -1};

void handle_write(int x);
void handle_read(int x);
void ensure_wal_is_open();
void remove_temp_snap();
void take_pics();
xnt load_snap();
void replay_wal(xnt x);
void dispatch(int conn_fd);

// establish TCP connection & send hello msg
static int initiate(int peer_id) {
    int backoff_ms = 100;
    int peerPort = 8080 + peer_id;
    while (true) {
        // a socket that failed connect() is unusable -- make a fresh one each try
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0)
            throw runtime_error("[initiate] socket failed: " + string(strerror(errno)));
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(peerPort);
        inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
        if (connect(fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) == 0) {
            // initiator sends his nodeID
            char msg[2] = { HELLO, static_cast<char>(myNodeID) };
            if (write(fd, msg, 2) == 2)
                return fd;
            // peer accepted then died mid-handshake -- transient, fall through and retry
        }
        close(fd);
        sleep_for(milliseconds(backoff_ms));
        backoff_ms = min(backoff_ms * 2, 3000);   // back off for real, cap at 3s
    }
}

// attaches listener to port
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

// called by acceptor.
// Reads hello msg & returns initiators nodeID
static int read_hello(int fd) {
    char first = 0;
    if (recv(fd, &first, 1, MSG_PEEK) != 1 || first != HELLO)
        return -1;
    char msg[2] = {};
    if (recv(fd, msg, 2, MSG_WAITALL) != 2)
        return -1;
    return (msg[1] >= 0 && msg[1] < NUM_NODES) ? msg[1] : -1;
}

// initiates tcp connection to assigned peer if wire breaks
// keeps READER on initiator's socket
static void keep_initiator_on_wire(int peer_id) {
    while (true) {
        int fd = initiate(peer_id); //! blocking
        my_fd_to[peer_id] = fd;
        dispatch(fd); // parks until the wire breaks
        my_fd_to[peer_id] = -1; // off the wire
        close(fd);
    }
}

// keeps READER on acceptor's socket
// called when initiator sends SYN packet
static void put_acceptor_on_wire(int fd) {
    int sender_id = read_hello(fd);

    if (sender_id != -1)
        my_fd_to[sender_id] = fd;

    dispatch(fd);

    if (sender_id != -1) {
        int stale = fd;
        my_fd_to[sender_id].compare_exchange_strong(stale, -1);
    }
    close(fd);
}

// sends messages to the proper handler
void dispatch(int conn_fd) {
    char op = 0;
    while (read(conn_fd, &op, 1) == 1) {

        if (op == WRITE)
            handle_write(conn_fd);

        else if (op == READ)
            handle_read(conn_fd);

        else break;   //?
    }
}

// parking lot for all nodes' main threads
// creates acceptor threads and calls put_acceptor_on_wire() when it receives SYN packet
static void accept_forever(int listener_fd) {
    while (true) {

        // every node's main thread parks here
        int conn_fd = accept(listener_fd, nullptr, nullptr);
        if (conn_fd < 0) continue;

        thread([conn_fd]() { put_acceptor_on_wire(conn_fd); }).detach();
    }
}

// (k v) (fn ln tlr) (i t CRC)
// restores DB from wal & connects cluster
int main(int argc, char *argv[]) {

    myNodeID = stoi(argv[1]);

    /*
    1. node0 sends op code to node2
    2. node2 is processing
    3. node0 dies, wire breaks
    4. node2 finishes processing
    5. node2 tries to ack through broken wire

    SIGPIPE normally kills node2
    SIG_IGN returns fail instead & continues process ,
    allowing node2 to stay on the wire
     */
    signal(SIGPIPE, SIG_IGN);

    ensure_wal_is_open();
    remove_temp_snap();
    xnt snap_idx = load_snap();
    truncate_wal(snap_idx);
    replay_wal(snap_idx);

    thread([] {
        take_pics();
    }).detach();

    int listener = attach_listener_to_port(8080 + myNodeID);

    for (int peer = myNodeID + 1; peer < NUM_NODES; ++peer)

        thread([peer] {
            keep_initiator_on_wire(peer);
        }).detach();

    accept_forever(listener);
}