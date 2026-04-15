#include "headers/replication.h"
#include "headers/globals.h"
#include "headers/wal.h"
#include "headers/store.h"
#include <iostream>
#include <sstream>
#include <thread>
#include <chrono>
#include <aws/sns/SNSClient.h>
#include <aws/sns/model/PublishRequest.h>
#include <aws/sqs/SQSClient.h>
#include <aws/sqs/model/ReceiveMessageRequest.h>
#include <aws/sqs/model/DeleteMessageRequest.h>

using namespace std;

static string extract_sns_message(const string& body) {
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
    return sns.Publish(req).IsSuccess();
}

void consume_replication() {
    Aws::SQS::SQSClient sqs;
    string queue_url = QUEUE_URLS[node_id];

    while (true) {
        Aws::SQS::Model::ReceiveMessageRequest req;
        req.SetQueueUrl(queue_url);
        req.SetMaxNumberOfMessages(10);
        req.SetWaitTimeSeconds(5);

        auto result = sqs.ReceiveMessage(req);
        if (!result.IsSuccess()) continue;

        for (auto& msg : result.GetResult().GetMessages()) {
            string raw = extract_sns_message(msg.GetBody());

            if (!raw.empty()) {
                istringstream ss(raw);
                wr w;
                uint32_t src{0}, seq_num{0}, checksum{0};
                ss >> w.t >> src >> seq_num >> w.k >> w.v >> checksum;
                w.src      = static_cast<uint8_t>(src);
                w.i        = seq_num;
                w.checksum = checksum;

                if (w.src != static_cast<uint8_t>(node_id)) {
                    append_wal(w);
                    apply_write(w);
                }
            }

            (void)sqs.DeleteMessage([&] {
                Aws::SQS::Model::DeleteMessageRequest del;
                del.SetQueueUrl(queue_url);
                del.SetReceiptHandle(msg.GetReceiptHandle());
                return del;
            }());
        }
    }
}