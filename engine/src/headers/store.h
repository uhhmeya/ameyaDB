#pragma once
#include <string>
#include "headers/wal.h"

void apply_write(const wr& w);
std::string apply_read(const std::string& k);