#include <iostream>
#include <thread>
#include <shared_mutex>
#include <unordered_map>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include "../headers/globals.h"
#include "../headers/handlers.h"
#include "../headers/sqs.h"
#include <filesystem>
#include "../headers/db.h"

#ifndef TESTING
    #include <aws/core/Aws.h>
#endif

/**
    === KV FORMAT ===
key = k0 --> k9
val = v0 --> v999

    === CLIENT TCP FORMAT ===
tcp wr = op klen k vlen v
tcp r = op klen k
*/

int node_id;
atomic<uint32_t> log_index{0};

unordered_map<string, string> db;
ofstream wal;

shared_mutex db_mutex;
mutex wal_mutex;

atomic<uint32_t> term{0};
atomic<int>      vote{-1};
atomic<Role>     role{FOLLOWER};

atomic<uint64_t> time_of_last_hb_received{0};

// put snaps & wal in src during local run_server_locally
#ifdef TESTING
    const string SNAP_DIR_PATH = "./snapshots/";
    const string WAL_PATH = "./wal.log";

// put snaps & wal in var/log/ameyaDB on ec2s
#else
    const string SNAP_DIR_PATH = "/var/log/ameyaDB/snapshots/";
    const string WAL_PATH = "/var/log/ameyaDB/wal.log";
#endif

int make_listener() {
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port        = htons(8080);
    bind(server_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    listen(server_fd, 10);
    cout << "node " << node_id << " listening on port 8080" << endl;
    return server_fd;
}

void dispatch(int client_fd) {
    char op = 0;

    // only reads first byte in socket
    while (read(client_fd, &op, 1) == 1) {

        if (op == WRITE)
            handle_write(client_fd);

        else if (op == READ)
            handle_read(client_fd);
    }

    close(client_fd);
}

int main(int argc, char* argv[]) {

    // skip
    #ifndef local_test
        Aws::SDKOptions options;
        InitAPI(options);
        create_directories("/var/log/ameyaDB");
    #endif

    node_id = stoi(argv[1]);

    create_directories(SNAP_DIR_PATH);
    wal.open(WAL_PATH, ios::app);

    // does not open WAL content
    if (!wal.is_open())
        throw runtime_error(" [main] could not setup write handler");

    // delete tmp snaps
    for (auto& entry : directory_iterator(SNAP_DIR_PATH))
        if (entry.path().extension() == ".tmp")
            remove(entry.path());

    int log_idx_of_last_entry_in_snap = load_snap();
    replay_wal(log_idx_of_last_entry_in_snap);

    // skip
    #ifndef local_test
        thread([]() {
            poll_SQS();
        }).detach();
    #endif

    thread([]() {
        take_pictures();
    }).detach();

    int server_fd = make_listener();

    while (true) {

        int client_fd = accept(server_fd, nullptr, nullptr);

        thread([client_fd]() {
            dispatch(client_fd);
        }).detach();

    }
}