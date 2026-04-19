#pragma once
#include "db.h"

bool publish_to_sns(const wr& w);
void consume_replication();