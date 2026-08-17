#include "../headers/globals.h"
#include <unistd.h>
#include <cstdint>

// imports
void apply_entry(const string& k, const string& v);
string apply_r(const string& k);


static constexpr xnt MAX_FIELD = 1u << 20;   // reject absurd lengths off the wire

// helpers
static bool read_tcp(int client_fd, void* buf, size_t n) {
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
static bool write_tcp(int client_fd, const void* buf, size_t n) {
    size_t sent = 0;
    while (sent < n) {
        ssize_t w = write(client_fd, static_cast<const char*>(buf) + sent, n - sent);
        if (w <= 0) {
            if (w < 0 && errno == EINTR) continue;
            return false;
        }
        sent += static_cast<size_t>(w);
    }
    return true;
}
static optional<pair<string,string>> read_kv(int client_fd) {
    xnt k_len{0}, v_len{0};

    if (!read_tcp(client_fd, &k_len, sizeof(k_len)) || k_len > MAX_FIELD) return nullopt;
    string k(k_len, '\0');
    if (k_len && !read_tcp(client_fd, &k[0], k_len)) return nullopt;

    if (!read_tcp(client_fd, &v_len, sizeof(v_len)) || v_len > MAX_FIELD) return nullopt;
    string v(v_len, '\0');
    if (v_len && !read_tcp(client_fd, &v[0], v_len)) return nullopt;

    return {{k, v}};
}
static optional<string> read_k(int client_fd) {
    xnt k_len{0};
    if (!read_tcp(client_fd, &k_len, sizeof(k_len)) || k_len > MAX_FIELD) return nullopt;
    string k(k_len, '\0');
    if (k_len && !read_tcp(client_fd, &k[0], k_len)) return nullopt;
    return k;
}

// handlers
bool handle_write(int client_fd) {
    auto kv = read_kv(client_fd);
    if (!kv) return false;

    auto [k, v] = *kv;
    apply_entry(k, v);

    uint8_t ack = 1;
    return write_tcp(client_fd, &ack, sizeof(ack));
}
bool handle_read(int client_fd) {
    auto k = read_k(client_fd);
    if (!k) return false;

    string v = apply_r(*k);
    xnt v_len = static_cast<xnt>(v.size());

    return write_tcp(client_fd, &v_len, sizeof(v_len))
        && write_tcp(client_fd, v.data(), v_len);
}