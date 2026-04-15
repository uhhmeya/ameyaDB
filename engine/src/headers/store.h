#pragma once
#include <string>
#include "wal.h"

void apply_write(const wr& w);
std::string apply_read(const std::string& k);