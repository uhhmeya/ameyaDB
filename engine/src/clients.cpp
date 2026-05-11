#include <iostream>
#include <thread>
#include <vector>
#include <string>
#include <cassert>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include "headers/globals.h"

static const int PORT              = 8080;
static const int NUM_THREADS       = 30;
static const int WRITES_PER_THREAD = 1000;
static const int KEYS_PER_THREAD   = 1000;

static mutex ack_txt_lock;
static vector<committed_wr> ack_txt;
static atomic<bool>      did_signal{false};
static int               min_acks_before_crash = 0;

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

static void send_wr(int num_writes, int thread_id) {
    int fd = connect_to_db();
    if (fd < 0) throw runtime_error("failed to connect to DB");

    vector<pair<string,string>> thread_local_wal;

    // send all writes concurrently
    for (int i = 0; i < num_writes; i++) {
        uint8_t op = WRITE;
        string k = "k" + to_string(thread_id * KEYS_PER_THREAD + i % KEYS_PER_THREAD);
        string v = "v" + to_string(rand() % 1000);
        uint32_t k_len = k.size();
        uint32_t v_len = v.size();
        write(fd, &op,      1);
        write(fd, &k_len,   4);
        write(fd, k.data(), k_len);
        write(fd, &v_len,   4);
        write(fd, v.data(), v_len);
        thread_local_wal.push_back({k, v});
    }

    cerr << "[thread " << thread_id << "] connected, fd=" << fd << "\n";
    for (int i = 0; i < num_writes; i++) {
        uint32_t log_idx = 0;

        // server crashed
        if (read(fd, &log_idx, sizeof(log_idx)) != sizeof(log_idx))
            break;
            /*
             * we don't know order of writes committed beyond this point
             * This is the correctness trade off
             */

        lock_guard lock(ack_txt_lock);

        // append k v idx
        ack_txt.push_back({thread_local_wal[i].first, thread_local_wal[i].second, log_idx});

        // is it time to crash?
        if (!did_signal.load() && (int)ack_txt.size() >= min_acks_before_crash && !did_signal.exchange(true)) {

            // dump global_wal into file
            ofstream f(ACK_PATH);
            for (auto& w : ack_txt)
                f << w.k << " " << w.v << " " << w.log_index << "\n";
            f.flush();
            f.close();

            // tell python to crash
            ofstream(SENTINEL_PATH).close();
        }
    }
    close(fd);
}

int main(int argc, char* argv[]) {

    if (argc < 2)
        throw runtime_error("usage: ./run_clients <min_acks_before_crash>");

    min_acks_before_crash = stoi(argv[1]);

    vector<thread> clients;
    for (int i = 0; i < NUM_THREADS; i++)
        clients.emplace_back(send_wr, WRITES_PER_THREAD, i);
    for (auto& t : clients)
        t.join();
    return 0;
}