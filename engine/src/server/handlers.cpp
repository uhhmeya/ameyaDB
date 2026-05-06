#include "../headers/handlers.h"
#include "../headers/globals.h"
#include "../headers/db.h"
#include "../headers/wr.h"
#include <thread>
#include <unistd.h>

#ifndef local_test
    #include <aws/sns/SNSClient.h>
    #include <aws/sns/model/PublishRequest.h>
#endif



#ifndef local_test
    static bool publish_SNS(const wr& w) {
        Aws::SNS::SNSClient sns;
        Aws::SNS::Model::PublishRequest req;
        req.SetTopicArn(SNS_TOPIC_ARN);
        req.SetMessage(serialize_wr(w));
        return sns.Publish(req).IsSuccess();
    }
#endif

// socket read utils
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
static optional<pair<string,string>> read_kv(int client_fd) {
    uint32_t k_len{0}, v_len{0};
    string k, v;
    bool did_read_properly = read_tcp(client_fd, &k_len, sizeof(k_len))
              && (k.resize(k_len), k_len == 0 || read_tcp(client_fd, &k[0], k_len))
              && read_tcp(client_fd, &v_len, sizeof(v_len))
              && (v.resize(v_len), v_len == 0 || read_tcp(client_fd, &v[0], v_len));

    if (!did_read_properly) return nullopt;
    return {{k, v}};
}
static optional<string> read_k(int client_fd) {
    uint32_t k_len{0};
    if (!read_tcp(client_fd, &k_len, sizeof(k_len))) return nullopt;
    string k(k_len, '\0');
    if (k_len > 0 && !read_tcp(client_fd, &k[0], k_len)) return nullopt;
    return k;
}

void handle_write(int client_fd) {

    auto kv = read_kv(client_fd);

    // client sends bad data
    if (!kv) {
        close(client_fd);
        return;
    }

    auto [k, v] = *kv;

    wr w;
    w.k                    = k;
    w.v                    = v;
    w.time_leader_received = now_ms(); // tcp write
    w.forwarding_node      = static_cast<uint8_t>(node_id);
    w.log_index            = ++log_index;
    w.checksum             = compute_checksum(w);

    apply_wr(w);

    #ifndef local_test
        while (!publish_SNS(w))
            sleep_for(milliseconds(100));
    #endif

    uint8_t ack = 1;
    write(client_fd, &ack, sizeof(ack));
}

void handle_read(int client_fd) {

    auto k = read_k(client_fd);

    // client sends bad data
    if (!k) {
        close(client_fd);
        return;
    }

    string val = apply_r(*k);

    // send v to client
    uint32_t v_len = static_cast<uint32_t>(val.size());
    write(client_fd, &v_len, sizeof(v_len));
    write(client_fd, val.data(), v_len);
}