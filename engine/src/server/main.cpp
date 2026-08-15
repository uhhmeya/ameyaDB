#include <iostream>
#include <thread>
#include <chrono>
#include <atomic>
#include <csignal>
#include <cstring>
#include <cerrno>
#include <string>
#include <vector>
#include <sys/socket.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netdb.h>

#include "../headers/globals.h"
#include "../headers/threads.h"

int myNodeID;
atomic<xnt> log_index{0};
vector<atomic<int>> my_fd_to;
atomic<int> relay_fd{-1};

// announce
void handle_write(int x);
void handle_read(int x);
void ensure_wal_is_open();
void remove_temp_snap();
void take_pics();
xnt load_snap();
void replay_wal(xnt x);
void attach_reader_to_tcp_wire(int peer_id);

// utils
static bool say_hi_to_relay(int fd) {
    string hello = "HELLO " + to_string(myNodeID) + "\n";
    return write(fd, hello.c_str(), hello.size()) == static_cast<ssize_t>(hello.size());
}
static string link_id(int a, int b) {
    return to_string(min(a, b)) + "<--->" + to_string(max(a, b));
}
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

    // a whole cluster can dial in at once -- let the backlog grow with it
    if (listen(listener_fd, max(10, NUM_NODES)) < 0)
        throw runtime_error("[attach_listener_to_port] listen failed: " + string(strerror(errno)));

    return listener_fd;
}
static int read_hello(int fd) {
    char first = 0;
    if (recv(fd, &first, 1, MSG_PEEK) != 1 || first != HELLO)
        return -1;
    char msg[1 + sizeof(int)] = {};
    if (recv(fd, msg, sizeof(msg), MSG_WAITALL) != static_cast<ssize_t>(sizeof(msg)))
        return -1;
    int sender_id = -1;
    memcpy(&sender_id, &msg[1], sizeof(sender_id));
    return (sender_id >= 0 && sender_id < NUM_NODES) ? sender_id : -1;
}

// constantly spams connection req to relay
// when relay is up, tcp wire will exist between node & relay
static int initiate_to_relay(const string &host, int port) {
    int backoff_ms = 100;
    while (true) {
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd >= 0) {
            sockaddr_in addr{};
            addr.sin_family = AF_INET;
            addr.sin_port = htons(port);

            bool resolved = inet_pton(AF_INET, host.c_str(), &addr.sin_addr) == 1;
            if (!resolved) {
                addrinfo hints{};
                hints.ai_family = AF_INET;
                hints.ai_socktype = SOCK_STREAM;
                addrinfo *res = nullptr;
                if (getaddrinfo(host.c_str(), nullptr, &hints, &res) == 0 && res) {
                    addr.sin_addr = reinterpret_cast<sockaddr_in *>(res->ai_addr)->sin_addr;
                    freeaddrinfo(res);
                    resolved = true;
                }
            }

            if (resolved && connect(fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) == 0)
                return fd;

            close(fd);
        }
        sleep_for(milliseconds(backoff_ms));
        backoff_ms = min(backoff_ms * 2, 3000);
    }
}

// constantly spams connection req to peer
// when peer is up, tcp wire will exist between peer & relay
static int initiate_to_peer(int peer_id) {
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
            // initiator sends his nodeID -- as a full int (same raw encoding
            // build_vote_request uses), so an id no longer has to fit in one char
            char msg[1 + sizeof(int)];
            msg[0] = HELLO;
            memcpy(&msg[1], &myNodeID, sizeof(myNodeID));
            if (write(fd, msg, sizeof(msg)) == static_cast<ssize_t>(sizeof(msg)))
                return fd;
            // peer accepted then died mid-handshake -- transient, fall through and retry
        }
        close(fd);
        sleep_for(milliseconds(backoff_ms));
        backoff_ms = min(backoff_ms * 2, 3000);   // back off for real, cap at 3s
    }
}

// keeps connection between node & relay
static void keep_relay_initiator_on_wire(string host, int port) {
    Thr.set_type("relay");

    while (true) {
        int fd = initiate_to_relay(host, port);   // blocks until connected

        if (!say_hi_to_relay(fd)) {
            close(fd);
            continue;
        }

        // connected :)
        relay_fd = fd;

        // disconnected :(
        char buf[1];
        read(fd, buf, sizeof(buf));
        relay_fd = -1;
        close(fd);
    }
}

// keeps connection between peers
static void keep_peer_initiator_on_wire(int peer_id) {
    Thr.set_type("initiator->" + to_string(peer_id));

    while (true) {

        /* creates tcp wire between 2 nodes
         * each node needs to have 2 threads, 1 for reading
         * and 1 for writing in order for the link to exist
        */
        int fd = initiate_to_peer(peer_id); // blocking
        my_fd_to[peer_id] = fd;

        attach_reader_to_tcp_wire(peer_id); //parks
        my_fd_to[peer_id] = -1;
        close(fd);
    }
}

//
static void put_acceptor_on_wire(int peerFD) {
    Thr.set_type("acceptor");

    int sender_id = read_hello(peerFD);
    if (sender_id == -1) {
        close(peerFD);
        return;
    }

    Thr.set_type(to_string(sender_id) + "<-acceptor");
    my_fd_to[sender_id] = peerFD;

    attach_reader_to_tcp_wire(sender_id);

    int stale = peerFD;
    my_fd_to[sender_id].compare_exchange_strong(stale, -1);
    close(peerFD);
}

void attach_reader_to_tcp_wire(int peer_id) {
    int peerFD = my_fd_to[peer_id].load();

    string msg = "reader attached to " + to_string(myNodeID) +
                 " on tcp wire " + to_string(myNodeID) + " --- " + to_string(peer_id);
    send_to_relay(relay_fd, msg);

    char op = 0;
    while (true) {
        if (read(peerFD, &op, 1) != 1)
            break;  //wire broke

        if (op == WRITE) {
            handle_write(peerFD);
        }

        else if (op == READ) {
            handle_read(peerFD);
        }
    }
}

static void accept_4ever(int listener) {

    // main thread parks here forever, accepting new peer connections
    while (true) {
        int peerFD = accept(listener, nullptr, nullptr);
        if (peerFD < 0) continue;
        thread([peerFD]() { put_acceptor_on_wire(peerFD); }).detach();
    }
}

// (k v) (fn ln tlr) (i t CRC)
int main(int argc, char *argv[]) {

    if (argc != 3)
        cerr << "usage: " << argv[0] << " <nodeID> <your_ip>\n";

    Thr.set_type("main");

    myNodeID = stoi(argv[1]);
    string relay_ip = argv[2];

    constexpr int relay_port = 9000;

    // spawn relay thread to connect node to relay
    thread([relay_ip] {
        keep_relay_initiator_on_wire(relay_ip, relay_port);
    }).detach();

    // park main thread until connected to relay
    while (relay_fd.load() == -1)
        sleep_for(milliseconds(50));

    // my_fd_to = (-1,-1,-1,-1,-1)
    my_fd_to = vector<atomic<int>>(NUM_NODES);
    for (auto &fd : my_fd_to) fd = -1;

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

    // TOY: node 0 heartbeats to the relay so we can verify the display path
    if (myNodeID == 0) {
        thread([] {
            Thr.set_type("toy");
            for (int i = 0; ; ++i) {
                send_to_relay(relay_fd, "toy message " + to_string(i));
                sleep_for(milliseconds(1000));
            }
        }).detach();
    }

    int myPort = 8080 + myNodeID;
    int listener = attach_listener_to_port(myPort);

    for (int peer = myNodeID + 1; peer < NUM_NODES; ++peer) {

        thread([peer] {
            keep_peer_initiator_on_wire(peer);
        }).detach();

    }

    accept_4ever(listener);
}