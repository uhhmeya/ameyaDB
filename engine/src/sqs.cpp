#include "headers/sqs.h"
#include "headers/globals.h"
#include "headers/db.h"
#include "headers/wr.h"
#include <sstream>
#include <aws/sns/SNSClient.h>
#include <aws/sns/model/PublishRequest.h>
#include <aws/sqs/SQSClient.h>
#include <aws/sqs/model/ReceiveMessageRequest.h>
#include <aws/sqs/model/DeleteMessageRequest.h>

static string extract_SNS(const string& body) {
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

static void del_SQS(Aws::SQS::SQSClient& sqs, const string& queue_url, const string& receipt) {
    Aws::SQS::Model::DeleteMessageRequest del;
    del.SetQueueUrl(queue_url);
    del.SetReceiptHandle(receipt);
    sqs.DeleteMessage(del);
}

void poll_SQS() {
    Aws::SQS::SQSClient sqs;
    string queue_url = QUEUE_URLS[node_id];

    while (true) {

        // poll
        Aws::SQS::Model::ReceiveMessageRequest req;
        req.SetQueueUrl(queue_url);
        req.SetMaxNumberOfMessages(10);
        req.SetWaitTimeSeconds(5);
        auto result = sqs.ReceiveMessage(req);
        if (!result.IsSuccess())
            continue;

        // extract
        for (auto& msg : result.GetResult().GetMessages()) {
            string raw = extract_SNS(msg.GetBody());

            // bad msg
            if (raw.empty()) {
                del_SQS(sqs, queue_url, msg.GetReceiptHandle());
                continue;
            }

            // parse
            istringstream ss(raw);
            string k, v;
            uint64_t time_leader_received{0};
            uint32_t forwarding_node{0}, log_index{0}, checksum{0};
            ss >> time_leader_received >> forwarding_node >> log_index >> k >> v >> checksum;

            // own message
            if (forwarding_node == static_cast<uint8_t>(node_id)) {
                del_SQS(sqs, queue_url, msg.GetReceiptHandle());
                continue;
            }

            wr w;
            w.k                    = k;
            w.v                    = v;
            w.time_leader_received = time_leader_received; // sqs write
            w.forwarding_node      = static_cast<uint8_t>(forwarding_node);
            w.log_index            = log_index;
            w.checksum             = compute_checksum(w);

            // partial write
            if (w.checksum != checksum) {
                del_SQS(sqs, queue_url, msg.GetReceiptHandle());
                continue;
            }

            apply_wr(w);
            del_SQS(sqs, queue_url, msg.GetReceiptHandle());
        }
    }
}