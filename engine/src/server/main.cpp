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
#include <netinet/tcp.h>
#include <fcntl.h>
#include <poll.h>

#include "../headers/globals.h"
#include "../headers/threads.h"

int myNodeID;
atomic<xnt> log_index{0};
vector<atomic<int>> my_fd_to;
atomic<int> relay_fd{-1};
atomic alive{false};
static mutex peer_write_mutex;

// announce
bool handle_write(int x);
bool handle_read(int x);
void ensure_wal_is_open();
void remove_temp_snap();
void take_pics();
xnt load_snap();
void replay_wal(xnt x);
void attach_reader_to_tcp_wire(int peer_id);
void raft_init();

static const string PEER_DOMAIN = "ameyadb.internal";
static const string RELAY_IP = "10.0.100.70";
constexpr int RELAY_PORT = 9000;
constexpr int CLIENT_PORT = 7000;

static const char *ALLOW_SCRIPT = "/usr/local/bin/ameyaDB-allow.sh";
static const char *CRASH_SCRIPT = "/usr/local/bin/ameyaDB-crash.sh";

// utils
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
static void set_keepalive(int fd) {
    int on = 1, idle = 5, intvl = 2, cnt = 3;
    setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &on, sizeof(on));
#ifdef __APPLE__
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPALIVE, &idle, sizeof(idle));
#else
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
#endif
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof(intvl));
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &cnt, sizeof(cnt));
}
static bool resolve_ipv4(const string &host, in_addr &out) {
    if (inet_pton(AF_INET, host.c_str(), &out) == 1)
        return true;

    addrinfo hints{};
    hints.ai_family   = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    addrinfo *res = nullptr;
    if (getaddrinfo(host.c_str(), nullptr, &hints, &res) != 0 || !res)
        return false;

    out = reinterpret_cast<sockaddr_in *>(res->ai_addr)->sin_addr;
    freeaddrinfo(res);
    return true;
}
static bool connect_with_timeout(int fd, const sockaddr_in &addr, int timeout_ms) {
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);

    int rc = connect(fd, reinterpret_cast<const sockaddr *>(&addr), sizeof(addr));
    if (rc != 0 && errno != EINPROGRESS) return false;

    if (rc != 0) {
        pollfd p{fd, POLLOUT, 0};
        if (poll(&p, 1, timeout_ms) != 1) return false;   // timed out

        int err = 0;
        socklen_t len = sizeof(err);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) != 0 || err != 0)
            return false;
    }

    fcntl(fd, F_SETFL, flags);   // back to blocking for the rest of the wire's life
    return true;
}

// tcp peer
static void put_acceptor_on_wire(int peerFD) {
    set_keepalive(peerFD);

    int sender_id = read_hello(peerFD);
    if (sender_id == -1) {
        close(peerFD);
        return;
    }

    my_fd_to[sender_id] = peerFD;

    attach_reader_to_tcp_wire(sender_id);

    int stale = peerFD;
    my_fd_to[sender_id].compare_exchange_strong(stale, -1);
    close(peerFD);
}
void attach_reader_to_tcp_wire(int peer_id) {
    int peerFD = my_fd_to[peer_id].load();
    send_to_relay("wire", to_string(myNodeID) + " " + to_string(peer_id) + " up");

    char op = 0;
    while (true) {
        if (read(peerFD, &op, 1) != 1) break;
        if      (op == WRITE) { if (!handle_write(peerFD)) break; }
        else if (op == READ)  { if (!handle_read(peerFD))  break; }
    }
    send_to_relay("wire", to_string(myNodeID) + " " + to_string(peer_id) + " down");
}

// tcp client
static void serve_client(int fd) {
    char op = 0;
    while (read(fd, &op, 1) == 1) {
        if      (op == WRITE) { if (!handle_write(fd)) break; }
        else if (op == READ)  { if (!handle_read(fd))  break; }
        else break;
    }
    close(fd);
}

// relay
static bool handle_relay_msg(int fd, const string &msg) {
    (void)fd;

    // allow.SH
    if (msg.rfind("connect ", 0) == 0) {
        string peers = msg.substr(8);
        string connect_cmd = "sudo " + string(ALLOW_SCRIPT) + " "
                           + to_string(myNodeID) + " " + peers;
        system(connect_cmd.c_str());
        alive = true;
        return true;
    }

    // crash.SH
    if (msg.rfind("terminate", 0) == 0) {
        int secs = (msg.size() > 10) ? stoi(msg.substr(10)) : 30;
        send_to_relay("crash", to_string(myNodeID) + " " + to_string(secs));
        string terminate_cmd = "sudo systemd-run --collect --quiet --unit=ameyaDB-chaos-"
                             + to_string(myNodeID) + " " + CRASH_SCRIPT
                             + " " + to_string(myNodeID) + " " + to_string(secs);
        system(terminate_cmd.c_str());
        return true;
    }

    return true;
}
static void attach_reader_to_relay(int fd) {
    string msg;
    char c;
    while (true) {
        ssize_t n = read(fd, &c, 1);
        if (n <= 0) return;          // relay wire broke
        if (c == '\n') {
            if (!handle_relay_msg(fd, msg)) return;
            msg.clear();
            continue;
        }
        msg += c;
    }
}

// constantly spams connection reqs
static int initiate_to_relay(const string &host, int port) {
    int backoff_ms = 100;

    while (true) {
        in_addr relay_ip{};
        if (!resolve_ipv4(host, relay_ip)) {
            sleep_for(milliseconds(backoff_ms));
            backoff_ms = min(backoff_ms * 2, 3000);
            continue;
        }

        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) {
            sleep_for(milliseconds(backoff_ms));
            backoff_ms = min(backoff_ms * 2, 3000);
            continue;
        }

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port   = htons(port);
        addr.sin_addr   = relay_ip;

        // A stopped bastion swallows the SYN exactly like a DROP rule does, so
        // an uncapped connect() would park here for ~2 minutes on every retry.
        if (connect_with_timeout(fd, addr, 2000))
            return fd;

        close(fd);
        sleep_for(milliseconds(backoff_ms));
        backoff_ms = min(backoff_ms * 2, 3000);
    }
}
static int initiate_to_peer(int peer_id) {
    int backoff_ms = 100;
    const int    peerPort = 8080 + peer_id;
    const string host     = "node-" + to_string(peer_id) + "." + PEER_DOMAIN;

    while (true) {
        // Re-resolve every attempt. Route53 rewrites these records whenever
        // terraform replaces an instance, and the TTL is 60s -- caching the
        // address once at startup would pin us to a dead IP for good.
        in_addr peer_ip{};
        if (!resolve_ipv4(host, peer_ip)) {
            sleep_for(milliseconds(backoff_ms));
            backoff_ms = min(backoff_ms * 2, 3000);
            continue;
        }

        // a socket that failed connect() is unusable -- make a fresh one each try
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0)
            throw runtime_error("[initiate] socket failed: " + string(strerror(errno)));

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port   = htons(peerPort);
        addr.sin_addr   = peer_ip;

        if (connect_with_timeout(fd, addr, 2000)) {
            set_keepalive(fd);
            char msg[1 + sizeof(int)];
            msg[0] = HELLO;
            memcpy(&msg[1], &myNodeID, sizeof(myNodeID));
            if (write(fd, msg, sizeof(msg)) == static_cast<ssize_t>(sizeof(msg)))
                return fd;
        }

        close(fd);
        sleep_for(milliseconds(backoff_ms));
        backoff_ms = min(backoff_ms * 2, 3000);
    }
}
static void keep_relay_initiator_on_wire(string host, int port) {
    while (true) {
        int fd = initiate_to_relay(host, port);   // blocks until connected
        relay_fd = fd;
        send_to_relay("hello", "hello");
        attach_reader_to_relay(fd); // blocks until relay wire breaks
        relay_fd = -1;
        close(fd);
    }
}
static void keep_initiator_on_wire(int peer_id) {
    while (true) {

        int fd = initiate_to_peer(peer_id);
        my_fd_to[peer_id] = fd;

        attach_reader_to_tcp_wire(peer_id);

        int stale = fd;
        my_fd_to[peer_id].compare_exchange_strong(stale, -1);
        close(fd);
    }
}

// peers
static void accept_4ever(int listener) {
    // main thread parks here forever, accepting new peer connections
    while (true) {
        int peerFD = accept(listener, nullptr, nullptr);
        if (peerFD < 0) continue;
        thread([peerFD]() { put_acceptor_on_wire(peerFD); }).detach();
    }
}
bool send_to_peer(int peer, const string &buf) {
    // my_fd_to is empty until the `alive` gate opens -- indexing it before
    // that is out of bounds, and this is reachable from raft's own thread.
    if (peer < 0 || peer >= static_cast<int>(my_fd_to.size())) return false;

    int fd = my_fd_to[peer].load();
    if (fd < 0) return false;

    lock_guard g(peer_write_mutex);

    size_t sent = 0;
    while (sent < buf.size()) {
        ssize_t w = write(fd, buf.data() + sent, buf.size() - sent);
        if (w <= 0) {
            if (w < 0 && errno == EINTR) continue;
            return false;
        }
        sent += static_cast<size_t>(w);
    }
    return true;
}

static void accept_clients_4ever(int listener) {
    while (true) {
        int fd = accept(listener, nullptr, nullptr);
        if (fd < 0) continue;
        thread([fd] { serve_client(fd); }).detach();
    }
}

// (k v) (fn ln tlr) (i t CRC)
int main(int argc, char *argv[]) {

    if (argc != 2) {
        cerr << "usage: " << argv[0] << " <nodeID>\n";
        return 1;
    }

    myNodeID = stoi(argv[1]);

    connect_to_CB();
    get_and_update_life_count(myNodeID);

    // connect to relay
    thread([] {
        keep_relay_initiator_on_wire(RELAY_IP, RELAY_PORT);
    }).detach();

    // wait until connected to relay
    while (relay_fd.load() == -1)
        sleep_for(milliseconds(50));

    cout << "node is playing dead\n";

    while (!alive.load())
        sleep_for(seconds(2));

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
    raft_init();

    thread([] {
        take_pics();
    }).detach();

    int myPort = 8080 + myNodeID;
    int listener = attach_listener_to_port(myPort);

    int client_listener = attach_listener_to_port(CLIENT_PORT);
    thread([client_listener] { accept_clients_4ever(client_listener); }).detach();

    for (int peer = myNodeID + 1; peer < NUM_NODES; ++peer) {
        thread([peer] {
            keep_initiator_on_wire(peer);
        }).detach();
    }
    accept_4ever(listener);
}