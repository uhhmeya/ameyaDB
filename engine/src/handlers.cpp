#include "headers/handlers.h"
#include "headers/globals.h"
#include "headers/protocol.h"
#include "headers/wal.h"
#include "headers/store.h"
#include "headers/replication.h"
#include <iostream>
#include <thread>
#include <chrono>
#include <unistd.h>

using namespace std;

void handle_write(int client_fd) {

    auto kv = read_kv(client_fd);

    // client sends bad data
    if (!kv) {
        close(client_fd);
        return;
    }

    auto [k, v] = *kv;

    wr w;
    w.k        = k;
    w.v        = v;
    w.t        = now_ms();
    w.src      = static_cast<uint8_t>(node_id);
    w.i        = ++seq;
    w.checksum = get_checksum(w);

    append_wal(w);
    apply_write(w);

    while (!publish_to_sns(w)) {
        cerr << "SNS publish failed for seq " << w.i << ", retrying..." << endl;
        this_thread::sleep_for(chrono::milliseconds(100));
    }

    uint8_t ack = 1;
    write(client_fd, &ack, sizeof(ack));
    close(client_fd);
}

void handle_read(int client_fd) {

    auto k = read_k(client_fd);

    // client sends bad data
    if (!k) {
        close(client_fd);
        return;
    }

    string val = apply_read(*k);

    // send v to client
    uint32_t v_len = static_cast<uint32_t>(val.size());
    write(client_fd, &v_len, sizeof(v_len));
    write(client_fd, val.data(), v_len);
    close(client_fd);
}