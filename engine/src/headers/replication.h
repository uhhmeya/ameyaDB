#pragma once
#include "wal.h"

bool publish_to_sns(const wr& w);
void consume_replication();