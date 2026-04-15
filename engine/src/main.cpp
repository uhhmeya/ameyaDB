#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <cstdint>
#include <chrono>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <atomic>
#include <thread>
#include <aws/core/Aws.h>
#include <aws/sns/SNSClient.h>
#include <aws/sns/model/PublishRequest.h>
#include <aws/sqs/SQSClient.h>
#include <aws/sqs/model/ReceiveMessageRequest.h>
#include <aws/sqs/model/DeleteMessageRequest.h>

using namespace std;

const string SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:540799520398:ameyaDB-replication";
const string QUEUE_URLS[3] = {
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-0",
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-1",
    "https://sqs.us-east-1.amazonaws.com/540799520398/ameyaDB-replication-node-2"
};

struct wr {
    string   k;
    string   v;
    uint64_t t{0};
    uint8_t  src{0};
    uint32_t i{0};
    uint32_t checksum{0};
};

uint64_t now_ms() {
    return chrono::duration_cast<chrono::milliseconds>(
        chrono::system_clock::now().time_since_epoch()
    ).count();
}

uint32_t get_checksum(const wr& w) {
    uint32_t crc = 0xFFFFFFFF;
    string data = to_string(w.t)   +
                  to_string(w.src) +
                  to_string(w.i)   +
                  w.k               +
                  w.v;
    for (char c : data) {
        crc ^= static_cast<uint8_t>(c);
        for (int j = 0; j < 8; j++)
            crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
    }
    return crc ^ 0xFFFFFFFF;
}

string serialize_wr(const wr& w) {
    return to_string(w.t)        + " " +
           to_string(w.src)      + " " +
           to_string(w.i)        + " " +
           w.k                    + " " +
           w.v                    + " " +
           to_string(w.checksum) + "\n";
}

void append_wal(const wr& w) {
    ofstream wal("/var/log/ameyaDB/wal.log", ios::app);
    wal << serialize_wr(w);
    wal.flush();
}

// extract the "Message" field from the SNS JSON envelope
string extract_sns_message(const string& body) {
    auto pos = body.find("\"Message\"");
    if (pos == string::npos) return "";
    pos = body.find('"', pos + 9);
    if (pos == string::npos) return "";
    auto end = body.find('"', pos + 1);
    if (end == string::npos) return "";
    string msg = body.substr(pos + 1, end - pos - 1);

    string result;
    for (size_t i = 0; i < msg.size(); i++) {
        if (msg[i] == '\\' && i + 1 < msg.size() && msg[i+1] == 'n') {
            result += '\n';
            i++;
        } else {
            result += msg[i];
        }
    }
    return result;
}

bool publish_to_sns(const wr& w) {
    Aws::SNS::SNSClient sns;
    Aws::SNS::Model::PublishRequest req;
    req.SetTopicArn(SNS_TOPIC_ARN);
    req.SetMessage(serialize_wr(w));
    auto result = sns.Publish(req);
    return result.IsSuccess();
}

void consume_replication(int node_id) {
    Aws::SQS::SQSClient sqs;
    string queue_url = QUEUE_URLS[node_id];

    while (true) {
        Aws::SQS::Model::ReceiveMessageRequest req;
        req.SetQueueUrl(queue_url);
        req.SetMaxNumberOfMessages(10);
        req.SetWaitTimeSeconds(5); // long polling

        auto result = sqs.ReceiveMessage(req);
        if (!result.IsSuccess()) continue;

        for (auto& msg : result.GetResult().GetMessages()) {
            string raw = extract_sns_message(msg.GetBody());

            if (!raw.empty()) {
                istringstream ss(raw);
                wr w;
                uint32_t src{0}, seq{0}, checksum{0};
                ss >> w.t >> src >> seq >> w.k >> w.v >> checksum;
                w.src      = static_cast<uint8_t>(src);
                w.i        = seq;
                w.checksum = checksum;

                if (w.src != static_cast<uint8_t>(node_id)) {
                    append_wal(w); // replicate write from another node
                }
            }

            // delete from queue regardless
            Aws::SQS::Model::DeleteMessageRequest del;
            del.SetQueueUrl(queue_url);
            del.SetReceiptHandle(msg.GetReceiptHandle());
            sqs.DeleteMessage(del);
        }
    }
}

void handle_client(int client_fd, int node_id, atomic<uint32_t>& seq) {

    auto read_tcp = [&](void* buf, size_t n) -> bool {
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
    };

    const uint32_t MAX_SIZE = 1 << 20; // 1MB
    uint32_t k_len{0}, v_len{0};
    string k, v;

    bool ok = read_tcp(&k_len, sizeof(k_len))              // how long is k?
              && k_len <= MAX_SIZE
              && (k.resize(k_len),                         // allocate space for k
                  k_len == 0 || read_tcp(&k[0], k_len))
              && read_tcp(&v_len, sizeof(v_len))            // how long is v?
              && v_len <= MAX_SIZE
              && (v.resize(v_len),                         // allocate space for v
                  v_len == 0 || read_tcp(&v[0], v_len));

    if (!ok) { close(client_fd); return; }

    wr w;
    w.k        = k;
    w.v        = v;
    w.t        = now_ms();
    w.src      = static_cast<uint8_t>(node_id);  // fix: C++ cast
    w.i        = ++seq;
    w.checksum = get_checksum(w);

    append_wal(w);

    while (!publish_to_sns(w)) {
        cerr << "SNS publish failed for seq " << w.i << ", retrying..." << endl;
        this_thread::sleep_for(chrono::milliseconds(100));
    }

    uint8_t ack = 1;
    write(client_fd, &ack, sizeof(ack));
    close(client_fd);
}

void start_server(int node_id) {
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port        = htons(8080);

    bind(server_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    listen(server_fd, 10);

    cout << "node " << node_id << " listening on port 8080" << endl;

    atomic<uint32_t> seq(0);
    while (true) {
        int client_fd = accept(server_fd, nullptr, nullptr);
        thread([client_fd, node_id, &seq]() {
            handle_client(client_fd, node_id, seq);
        }).detach();
    }
}

int main(int argc, char* argv[]) {
    Aws::SDKOptions options;
    InitAPI(options);

    if (argc < 2) {
        cerr << "usage: ./node <node_id>" << endl;
        ShutdownAPI(options);
        return 1;
    }

    int node_id = stoi(argv[1]);
    cout << "node " << node_id << " starting..." << endl;

    thread([node_id]() {
        consume_replication(node_id);
    }).detach();

    start_server(node_id);

    ShutdownAPI(options);
    return 0;
}