#include "../headers/globals.h"
#include <unistd.h>
#include <cstdint>
#include <cstring>

string apply_r(const string& k);

bool am_i_leader();
int  who_is_leader();
bool onWrite(const string& k, const string& v);
void onVReq(int c_ID, xnt c_Term, xnt c_LogIDX, xnt c_LogTERM);
void onVRes(int c_ID, xnt c_Term, bool was_vote_granted);
void onAE(int leader_id, xnt term, xnt last_log_idx_in_old_batch, xnt last_log_term_in_old_batch, xnt leader_commit,
    const vector<entry>& suffix);
void onAERes(int f_ID, xnt f_Term, xnt last_log_idx_in_next_old_batch, bool was_ae_accepted);
void onSnap(int leader_id, xnt term, const string& snap);

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

    if (!read_tcp(client_fd, &k_len, sizeof(k_len))) return nullopt;
    string k(k_len, '\0');
    if (k_len && !read_tcp(client_fd, &k[0], k_len)) return nullopt;

    if (!read_tcp(client_fd, &v_len, sizeof(v_len))) return nullopt;
    string v(v_len, '\0');
    if (v_len && !read_tcp(client_fd, &v[0], v_len)) return nullopt;

    return {{k, v}};
}
static optional<string> read_k(int client_fd) {
    xnt k_len{0};
    if (!read_tcp(client_fd, &k_len, sizeof(k_len))) return nullopt;
    string k(k_len, '\0');
    if (k_len && !read_tcp(client_fd, &k[0], k_len)) return nullopt;
    return k;
}
static optional<entry> read_entry(int peer_fd) {
    auto kv = read_kv(peer_fd);
    if (!kv) return nullopt;

    entry e;
    e.wr.k = kv->first;
    e.wr.v = kv->second;
    if (!read_tcp(peer_fd, &e.stats, sizeof(e.stats))) return nullopt;
    if (!read_tcp(peer_fd, &e.log_index, sizeof(e.log_index))) return nullopt;
    if (!read_tcp(peer_fd, &e.term, sizeof(e.term))) return nullopt;
    if (!read_tcp(peer_fd, &e.checksum, sizeof(e.checksum))) return nullopt;
    if (compute_checksum(e) != e.checksum) return nullopt;
    return e;
}
static bool reply(int client_fd, Status status, int leader_hint) {
    char buf[1 + sizeof(int)];
    buf[0] = static_cast<char>(status);
    memcpy(&buf[1], &leader_hint, sizeof(leader_hint));
    return write_tcp(client_fd, buf, sizeof(buf));
}

bool handle_write(int client_fd) {
    auto kv = read_kv(client_fd);
    if (!kv) return false;

    if (!am_i_leader()) {
        int leader_id = who_is_leader();
        if (leader_id == NO_LEADER)
            return reply(client_fd, IDK, -1);
        return reply(client_fd, I_AM_NOT_LEADER, leader_id);
    }

    auto [k, v] = *kv;
    if (!onWrite(k, v))
        return reply(client_fd, IDK, -1);

    return reply(client_fd, I_AM_LEADER, myNodeID);
}

bool handle_read(int client_fd) {
    auto k = read_k(client_fd);
    if (!k) return false;

    string v = apply_r(*k);
    xnt v_len = static_cast<xnt>(v.size());

    return write_tcp(client_fd, &v_len, sizeof(v_len))
        && write_tcp(client_fd, v.data(), v_len);
}
bool handle_vreq(int peer_fd) {
    int c_ID{0};
    xnt c_Term{0}, c_LogIDX{0}, c_LogTERM{0};

    if (!read_tcp(peer_fd, &c_ID, sizeof(c_ID))) return false;
    if (!read_tcp(peer_fd, &c_Term, sizeof(c_Term))) return false;
    if (!read_tcp(peer_fd, &c_LogIDX, sizeof(c_LogIDX))) return false;
    if (!read_tcp(peer_fd, &c_LogTERM, sizeof(c_LogTERM))) return false;

    onVReq(c_ID, c_Term, c_LogIDX, c_LogTERM);
    return true;
}
bool handle_vres(int peer_fd) {
    int c_ID{0};
    xnt c_Term{0};
    bool yes_or_no{false};

    if (!read_tcp(peer_fd, &c_ID, sizeof(c_ID))) return false;
    if (!read_tcp(peer_fd, &c_Term, sizeof(c_Term))) return false;
    if (!read_tcp(peer_fd, &yes_or_no, sizeof(yes_or_no))) return false;

    onVRes(c_ID, c_Term, yes_or_no);
    return true;
}
bool handle_ae(int peer_fd) {
    int leader_id{0};
    xnt term{0}, last_log_idx_in_old_batch{0}, last_log_term_in_old_batch{0}, leader_commit{0}, n{0};

    if (!read_tcp(peer_fd, &leader_id, sizeof(leader_id))) return false;
    if (!read_tcp(peer_fd, &term, sizeof(term))) return false;
    if (!read_tcp(peer_fd, &last_log_idx_in_old_batch, sizeof(last_log_idx_in_old_batch))) return false;
    if (!read_tcp(peer_fd, &last_log_term_in_old_batch, sizeof(last_log_term_in_old_batch))) return false;
    if (!read_tcp(peer_fd, &leader_commit, sizeof(leader_commit))) return false;
    if (!read_tcp(peer_fd, &n, sizeof(n))) return false;

    vector<entry> suffix;
    for (xnt i = 0; i < n; i++) {
        auto e = read_entry(peer_fd);
        if (!e) return false;
        suffix.push_back(*e);
    }

    onAE(leader_id, term, last_log_idx_in_old_batch, last_log_term_in_old_batch, leader_commit, suffix);
    return true;
}
bool handle_aeres(int peer_fd) {
    int f_ID{0};
    xnt f_Term{0}, last_log_idx_in_next_old_batch{0};
    bool was_ae_accepted{false};

    if (!read_tcp(peer_fd, &f_ID, sizeof(f_ID))) return false;
    if (!read_tcp(peer_fd, &f_Term, sizeof(f_Term))) return false;
    if (!read_tcp(peer_fd, &last_log_idx_in_next_old_batch, sizeof(last_log_idx_in_next_old_batch))) return false;
    if (!read_tcp(peer_fd, &was_ae_accepted, sizeof(was_ae_accepted))) return false;

    onAERes(f_ID, f_Term, last_log_idx_in_next_old_batch, was_ae_accepted);
    return true;
}
bool handle_snap(int peer_fd) {
    int leader_id{0};
    xnt term{0}, snap_len{0};

    if (!read_tcp(peer_fd, &leader_id, sizeof(leader_id))) return false;
    if (!read_tcp(peer_fd, &term, sizeof(term))) return false;
    if (!read_tcp(peer_fd, &snap_len, sizeof(snap_len))) return false;

    string snap(snap_len, '\0');
    if (snap_len && !read_tcp(peer_fd, &snap[0], snap_len)) return false;

    onSnap(leader_id, term, snap);
    return true;
}