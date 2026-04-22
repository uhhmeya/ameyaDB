#pragma once
#include "db.h"

bool publish_SNS(const wr& w);
void poll_SQS();