#include <iostream>
#include <thread>
#include <shared_mutex>
#include <unordered_map>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <aws/core/Aws.h>
#include "headers/globals.h"
#include "headers/handlers.h"
#include "headers/replication.h"

using namespace std;

// globals
int node_id;
atomic<uint32_t> seq{0};
unordered_map<string, string> db;
shared_mutex db_mutex;


// tcp wr = 0 klen k vlen v
// tcp r = 1 klen k

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

    // client DC before sending anything
    if (read(client_fd, &op, 1) != 1) {
        close(client_fd);
        return;
    }

    // only 1 byte is read

    if (op == 1)
        handle_write(client_fd);

    else if (op == 2)
        handle_read(client_fd);

    else
        close(client_fd);
}

int main(char* argv[]) {

    Aws::SDKOptions options;
    InitAPI(options);
    node_id = stoi(argv[1]);

    // bthread
    thread([]() {
        consume_replication();
    }).detach();

    int server_fd = make_listener();

    while (true) {

        int client_fd = accept(server_fd, nullptr, nullptr);

        // worker
        thread([client_fd]() {
            dispatch(client_fd);
        }).detach();

    }
}