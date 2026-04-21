#pragma once
#include "db.h"

bool publish_to_sns(const wr& w);
void poll_SQS(const std::string& queue_url);