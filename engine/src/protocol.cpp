#include "headers/protocol.h"
#include <unistd.h>
#include <cerrno>

using namespace std;

bool read_tcp(int client_fd, void* buf, size_t n) {
    size_t received = 0;

    while (received < n) {
        ssize_t r = read(client_fd, static_cast<char*>(buf) + received, n - received);
        if (r == 0) return false;
        if (r < 0) {
            if (errno == EINTR) continue;
            return false;
        }

        received += static_cast<size_t>(r);
    }
    return true;
}

optional<pair<string,string>> read_kv(int client_fd) {
    uint32_t k_len{0}, v_len{0};
    string k, v;
    bool did_read_properly = read_tcp(client_fd, &k_len, sizeof(k_len))
              && (k.resize(k_len), k_len == 0 || read_tcp(client_fd, &k[0], k_len))
              && read_tcp(client_fd, &v_len, sizeof(v_len))
              && (v.resize(v_len), v_len == 0 || read_tcp(client_fd, &v[0], v_len));

    if (!did_read_properly) return nullopt;
    return {{k, v}};
}

optional<string> read_k(int client_fd) {
    uint32_t k_len{0};
    if (!read_tcp(client_fd, &k_len, sizeof(k_len))) return nullopt;
    string k(k_len, '\0');
    if (k_len > 0 && !read_tcp(client_fd, &k[0], k_len)) return nullopt;
    return k;
}