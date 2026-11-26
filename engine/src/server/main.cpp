#include <iostream>
#include <thread>
#include <chrono>
#include <atomic>
#include <csignal>
#include <cstring>
#include <cerrno>
#include <string>
#include <vector>
#include <utility>
#include <deque>
#include <mutex>
#include <condition_variable>
#include <sys/socket.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netdb.h>
#include <netinet/tcp.h>
#include <fcntl.h>
#include <poll.h>
#include <sstream>
#include <algorithm>

#include "../headers/globals.h"
#include "../headers/threads.h"


int myNodeID;
atomic<xnt> log_index{0};
vector<atomic<int>> my_fd_to;
atomic<int> relay_fd{-1};
atomic participating{false};

struct outbox_msg {
    steady_clock::time_point send_at;
    string buf;
};
static mutex outbox_mutex[NUM_NODES];
static condition_variable outbox_cv[NUM_NODES];
static deque<outbox_msg> outbox[NUM_NODES];
static steady_clock::time_point last_send_at[NUM_NODES];
static mutex wire_mutex[NUM_NODES];

static atomic<int> link_delay_ms[NUM_NODES];
static atomic<int> link_jitter_ms[NUM_NODES];
static atomic<int> link_drop_pct[NUM_NODES];
static atomic<int> disk_stall_ms{0};
static mutex flags_mutex;
static unordered_map<string, int> flags;

static atomic<long long> relay_epoch{-1};
static atomic<long long> loaded_epoch{-1};
static atomic<bool> keep_old_data{false};

static atomic<unsigned long long> msgs_sent[SNAP + 1];
static atomic<unsigned long long> msgs_dropped{0};

bool handle_write(int x);
bool handle_read(int x);
bool handle_vreq(int x);
bool handle_vres(int x);
bool handle_ae(int x);
bool handle_aeres(int x);
bool handle_snap(int x);
string db_state();
xnt get_commit_idx();
xnt get_cur_term();
bool am_i_caught_up();
void ensure_wal_is_open();
void remove_temp_snap();
void take_pics();
pair<xnt, xnt> load_snap();
void replay_wal(xnt x);
void attach_reader_to_peer_wire(int peer_id);
void raft_init();
void truncate_wal(xnt snap_idx, xnt last_term);

static const string PEER_DOMAIN = "ameyadb.internal";
static const string RELAY_IP = "10.0.100.70";
constexpr int RELAY_PORT = 9000;
constexpr int CLIENT_PORT = 7000;

static const string DATA_DIR = "../output";

static const char *ALLOW_SCRIPT = "/usr/local/bin/ameyaDB-allow.sh";
static const char *CRASH_SCRIPT = "/usr/local/bin/ameyaDB-crash.sh";

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
    int on = 1, idle = 5, intvl = 2, cnt = 3, user_timeout = 3000;
    setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &on, sizeof(on));
#ifdef __APPLE__
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPALIVE, &idle, sizeof(idle));
#else
    setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
    setsockopt(fd, IPPROTO_TCP, TCP_USER_TIMEOUT, &user_timeout, sizeof(user_timeout));
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
        if (poll(&p, 1, timeout_ms) != 1) return false;

        int err = 0;
        socklen_t len = sizeof(err);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) != 0 || err != 0)
            return false;
    }

    fcntl(fd, F_SETFL, flags);
    return true;
}

static void hang_up(int peer_id, int fd) {
    shutdown(fd, SHUT_RDWR);

    lock_guard w(wire_mutex[peer_id]);
    int stale = fd;
    my_fd_to[peer_id].compare_exchange_strong(stale, -1);
    close(fd);
}

static void put_acceptor_on_wire(int peerFD) {
    set_keepalive(peerFD);

    int sender_id = read_hello(peerFD);
    if (sender_id == -1) {
        close(peerFD);
        return;
    }

    my_fd_to[sender_id] = peerFD;

    attach_reader_to_peer_wire(sender_id);

    hang_up(sender_id, peerFD);
}

static bool route_to_handler(int peerFD, char op) {
    if      (op == WRITE) return handle_write(peerFD);
    else if (op == READ)  return handle_read(peerFD);
    else if (op == VREQ)  return handle_vreq(peerFD);
    else if (op == VRES)  return handle_vres(peerFD);
    else if (op == APPEND_ENTRIES) return handle_ae(peerFD);
    else if (op == AERES) return handle_aeres(peerFD);
    else if (op == SNAP)  return handle_snap(peerFD);

    return false;
}

void attach_reader_to_peer_wire(int peer_id) {
    int peerFD = my_fd_to[peer_id].load();

    char op = 0;
    while (true) {
        if (read(peerFD, &op, 1) != 1) break;
        if (!route_to_handler(peerFD, op)) break;
    }

    send_to_relay("unreachable", to_string(peer_id));
}

static void serve_client(int fd) {
    char op = 0;
    while (read(fd, &op, 1) == 1) {
        if      (op == WRITE) { if (!handle_write(fd)) break; }
        else if (op == READ)  { if (!handle_read(fd))  break; }
        else break;
    }
    close(fd);
}

int get_flag(const string &name, int fallback) {
    lock_guard g(flags_mutex);
    auto it = flags.find(name);
    return it == flags.end() ? fallback : it->second;
}
void disk_stall() {
    int ms = disk_stall_ms.load();
    if (ms > 0) sleep_for(milliseconds(ms));
}
string net_stat() {
    int conn = 0;
    for (int peer = 0; peer < NUM_NODES; peer++)
        if (my_fd_to[peer].load() >= 0) conn |= 1 << peer;

    return to_string(conn) + " " + to_string(msgs_sent[VREQ].load()) + " "
         + to_string(msgs_sent[APPEND_ENTRIES].load()) + " " + to_string(msgs_sent[SNAP].load()) + " "
         + to_string(msgs_dropped.load());
}

static void freeze_myself(const string &msg) {
    istringstream ss(msg);
    string kind;
    int stop_ms = 0, run_ms = 0, total_ms = 0;
    ss >> kind >> stop_ms >> run_ms >> total_ms;

    string pid = to_string(getpid());
    string stop_secs = to_string(stop_ms / 1000.0);
    string run_secs = to_string(run_ms / 1000.0);
    string freeze_cmd;

    if (kind == "pause")
        freeze_cmd = "(kill -STOP " + pid + "; sleep " + stop_secs + "; kill -CONT " + pid + ")";
    else
        freeze_cmd = "(end=$(($(date +%s%N) / 1000000 + " + to_string(total_ms) + ")); "
                     "while [ $(($(date +%s%N) / 1000000)) -lt $end ]; do "
                     "kill -STOP " + pid + " || break; sleep " + stop_secs + "; "
                     "kill -CONT " + pid + "; sleep " + run_secs + "; done; kill -CONT " + pid + ")";

    send_to_relay("fault", msg);
    system((freeze_cmd + " >/dev/null 2>&1 &").c_str());
}

static bool done_processing() {
    for (int peer = 0; peer < NUM_NODES; ++peer) {
        lock_guard g(outbox_mutex[peer]);
        if (!outbox[peer].empty()) return false;
    }
    if (!am_i_caught_up()) return false;
    xnt commit_idx = get_commit_idx();
    return get_applied_idx() == commit_idx && get_log_idx() == commit_idx;
}
static bool handle_relay_msg(int fd, const string &msg) {
    (void)fd;

    if (msg.rfind("epoch ", 0) == 0) {
        istringstream ss(msg.substr(6));
        long long epoch = -1;
        int keep = 0;
        ss >> epoch >> keep;

        relay_epoch = epoch;
        keep_old_data = keep == 1;

        if (loaded_epoch.load() != -1 && loaded_epoch.load() != epoch)
            _exit(0);
        return true;
    }

    if (msg.rfind("flags", 0) == 0) {
        istringstream ss(msg.substr(5));
        string flag;

        lock_guard g(flags_mutex);
        flags.clear();
        while (ss >> flag) {
            auto eq = flag.find('=');
            if (eq == string::npos) continue;
            flags[flag.substr(0, eq)] = atoi(flag.substr(eq + 1).c_str());
        }
        return true;
    }

    if (msg.rfind("connect ", 0) == 0) {
        string peers = msg.substr(8);
        string connect_cmd = "sudo " + string(ALLOW_SCRIPT) + " "
                           + to_string(myNodeID) + " " + peers;
        system(connect_cmd.c_str());
        participating = true;

        send_to_relay("fault", msg);
        return true;
    }

    if (msg.rfind("terminate", 0) == 0) {
        string secs = (msg.size() > 10) ? msg.substr(10) : "30";
        if (secs.empty() || secs.find_first_not_of("0123456789.") != string::npos) secs = "30";

        send_to_relay("crash", to_string(myNodeID) + " " + secs);


        string terminate_cmd = "sudo systemd-run --collect --quiet --unit=ameyaDB-chaos-"
                             + to_string(myNodeID) + " " + CRASH_SCRIPT
                             + " " + to_string(myNodeID) + " " + secs;
        system(terminate_cmd.c_str());
        return true;
    }

    if (msg.rfind("link ", 0) == 0) {
        istringstream ss(msg.substr(5));
        string peer;
        int delay_ms = 0, jitter_ms = 0, drop_pct = 0;
        ss >> peer >> delay_ms >> jitter_ms >> drop_pct;

        for (int p = 0; p < NUM_NODES; p++) {
            if (peer != "all" && peer != to_string(p)) continue;
            link_delay_ms[p] = delay_ms;
            link_jitter_ms[p] = jitter_ms;
            link_drop_pct[p] = drop_pct;
        }
        return true;
    }

    if (msg.rfind("disk ", 0) == 0) {
        disk_stall_ms = atoi(msg.substr(5).c_str());
        return true;
    }

    if (msg.rfind("pause ", 0) == 0 || msg.rfind("limp ", 0) == 0) {
        freeze_myself(msg);
        return true;
    }

    if (msg.rfind("writes_stopped", 0) == 0) {
        thread([] {
            while (!done_processing())
                sleep_for(milliseconds(50));
            send_to_relay("done", "done");
        }).detach();
        return true;
    }

    if (msg.rfind("agreement_check_req", 0) == 0) {
        send_to_relay("agreement_check_res", db_state());
        return true;
    }

    return true;
}
static void attach_reader_to_relay(int fd) {
    string msg;
    char c;
    while (true) {
        ssize_t n = read(fd, &c, 1);
        if (n <= 0) return;
        if (c == '\n') {
            if (!handle_relay_msg(fd, msg)) return;
            msg.clear();
            continue;
        }
        msg += c;
    }
}

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
        in_addr peer_ip{};
        if (!resolve_ipv4(host, peer_ip)) {
            sleep_for(milliseconds(backoff_ms));
            backoff_ms = min(backoff_ms * 2, 500);
            continue;
        }

        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0)
            throw runtime_error("[initiate] socket failed: " + string(strerror(errno)));

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port   = htons(peerPort);
        addr.sin_addr   = peer_ip;

        if (connect_with_timeout(fd, addr, 500)) {
            set_keepalive(fd);
            char msg[1 + sizeof(int)];
            msg[0] = HELLO;
            memcpy(&msg[1], &myNodeID, sizeof(myNodeID));
            if (write(fd, msg, sizeof(msg)) == static_cast<ssize_t>(sizeof(msg)))
                return fd;
        }

        close(fd);
        sleep_for(milliseconds(backoff_ms));
        backoff_ms = min(backoff_ms * 2, 500);
    }
}
static void keep_relay_initiator_on_wire(string host, int port) {
    while (true) {
        int fd = initiate_to_relay(host, port);
        relay_fd = fd;
        send_to_relay("hello", "hello");
        if (participating.load()) send_to_relay("participating", "participating");
        attach_reader_to_relay(fd);
        relay_fd = -1;
        close(fd);
    }
}
static void keep_initiator_on_wire(int peer_id) {
    while (true) {

        int fd = initiate_to_peer(peer_id);
        my_fd_to[peer_id] = fd;

        attach_reader_to_peer_wire(peer_id);

        hang_up(peer_id, fd);
    }
}

static void accept_4ever(int listener) {
    while (true) {
        int peerFD = accept(listener, nullptr, nullptr);
        if (peerFD < 0) continue;
        thread([peerFD]() { put_acceptor_on_wire(peerFD); }).detach();
    }
}

bool Psend(int peer, const string &buf) {
    if (peer < 0 || peer >= static_cast<int>(my_fd_to.size())) return false;

    int fd = my_fd_to[peer].load();
    if (fd < 0) return false;

    int drop_pct = link_drop_pct[peer].load();
    if (drop_pct > 0 && rand_sleep_timer_ms(1, 100) <= drop_pct) {
        msgs_dropped++;
        return true;
    }

    auto send_at = steady_clock::now();
    int delay_ms = link_delay_ms[peer].load();
    if (delay_ms > 0)
        send_at += milliseconds(delay_ms + rand_sleep_timer_ms(0, link_jitter_ms[peer].load()));

    {
        lock_guard g(outbox_mutex[peer]);
        if (outbox[peer].size() >= 1000) return false;

        send_at = max(send_at, last_send_at[peer]);
        last_send_at[peer] = send_at;
        outbox[peer].push_back({send_at, buf});
    }
    if (!buf.empty() && buf[0] >= 0 && buf[0] <= SNAP) msgs_sent[static_cast<int>(buf[0])]++;
    outbox_cv[peer].notify_one();
    return true;
}

static void drain_outbox_4ever(int peer) {
    while (true) {
        string buf;
        {
            unique_lock g(outbox_mutex[peer]);
            outbox_cv[peer].wait(g, [peer] { return !outbox[peer].empty(); });

            auto send_at = outbox[peer].front().send_at;
            if (send_at > steady_clock::now()) {
                g.unlock();
                sleep_until(send_at);
                continue;
            }

            buf = std::move(outbox[peer].front().buf);
            outbox[peer].pop_front();
        }

        if (link_drop_pct[peer].load() >= 100) {
            msgs_dropped++;
            continue;
        }

        lock_guard w(wire_mutex[peer]);
        int fd = my_fd_to[peer].load();
        if (fd < 0) continue;

        size_t sent = 0;
        while (sent < buf.size()) {
            ssize_t w = write(fd, buf.data() + sent, buf.size() - sent);
            if (w <= 0) {
                if (w < 0 && errno == EINTR) continue;
                break;
            }
            sent += static_cast<size_t>(w);
        }
    }
}

static void accept_clients_4ever(int listener) {
    while (true) {
        int fd = accept(listener, nullptr, nullptr);
        if (fd < 0) continue;
        thread([fd] { serve_client(fd); }).detach();
    }
}

static void wipe_data_if_new_epoch() {
    const long long epoch = relay_epoch.load();
    loaded_epoch = epoch;
    if (epoch == -1) return;

    const string epoch_path = DATA_DIR + "/epoch";

    long long saved_epoch = -1;
    ifstream saved(epoch_path);
    saved >> saved_epoch;
    if (saved_epoch == epoch) return;

    if (keep_old_data.load()) {
        error_code ec;
        const string archive = DATA_DIR + "/archive";
        const string grave = archive + "/" + to_string(saved_epoch);
        create_directories(grave, ec);
        for (const char *name : {"snaps", "wal.txt", "raft.txt"})
            rename(path(DATA_DIR) / name, path(grave) / name, ec);

        vector<path> graves;
        for (auto &dir : directory_iterator(archive, ec)) graves.push_back(dir.path());
        sort(graves.begin(), graves.end());
        for (size_t i = 0; i + 3 < graves.size(); i++) remove_all(graves[i], ec);
    }

    remove_all(DATA_DIR + "/snaps");
    remove(DATA_DIR + "/wal.txt");
    remove(DATA_DIR + "/wal.txt.tmp");
    remove(DATA_DIR + "/raft.txt");
    remove(DATA_DIR + "/raft.tmp");

    create_directories(DATA_DIR);
    ofstream new_epoch(epoch_path);
    new_epoch << epoch << "\n";
    send_to_relay("wiped", to_string(epoch));
}

int main(int argc, char *argv[]) {

    myNodeID = stoi(argv[1]);

    connect_to_CB();
    get_and_update_life_count(myNodeID);

    thread([] {
        keep_relay_initiator_on_wire(RELAY_IP, RELAY_PORT);
    }).detach();
    while (relay_fd.load() == -1)
        sleep_for(milliseconds(50));

    thread(drain_notes_4ever).detach();

    while (!participating.load())
        sleep_for(milliseconds(50));
    send_to_relay("participating", "participating");

    my_fd_to = vector<atomic<int>>(NUM_NODES);
    for (auto &fd : my_fd_to) fd = -1;

    for (int peer = 0; peer < NUM_NODES; ++peer) {
        thread([peer] {
            drain_outbox_4ever(peer);
        }).detach();
    }

    signal(SIGPIPE, SIG_IGN);

    wipe_data_if_new_epoch();
    ensure_wal_is_open();
    remove_temp_snap();
    auto [snap_idx, last_term] = load_snap();
    truncate_wal(snap_idx, last_term);
    replay_wal(snap_idx);
    raft_init();
    note("booted", to_string(loaded_epoch.load()) + " " + to_string(get_log_idx()) + " " + to_string(get_cur_term()));

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
