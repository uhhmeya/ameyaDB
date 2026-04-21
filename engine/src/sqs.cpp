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

void poll_SQS(const string& queue_url) {
    Aws::SQS::SQSClient sqs;

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
            string raw = extract_sns_message(msg.GetBody());

            // early return : extract error
            if (raw.empty()) {
                sqs.DeleteMessage([&] {
                    Aws::SQS::Model::DeleteMessageRequest del;
                    del.SetQueueUrl(queue_url);
                    del.SetReceiptHandle(msg.GetReceiptHandle());
                    return del;
                }());
                continue;
            }

            // parse
            istringstream ss(raw);
            string k, v;
            uint64_t t{0};
            uint32_t src{0}, seq_num{0}, checksum{0};
            ss >> t >> src >> seq_num >> k >> v >> checksum;

            // apply
            if (src != static_cast<uint8_t>(node_id)) {
                wr w = make_foreign_wr(k, v, static_cast<uint8_t>(src), seq_num, t);
                apply_wr(w);
            }

            // remove from queue
            sqs.DeleteMessage([&] {
                Aws::SQS::Model::DeleteMessageRequest del;
                del.SetQueueUrl(queue_url);
                del.SetReceiptHandle(msg.GetReceiptHandle());
                return del;
            }());
        }
    }
}

