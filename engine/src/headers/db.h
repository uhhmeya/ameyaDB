#pragma once
#include "wr.h"

void apply_wr(const wr& w);
std::string apply_r(const std::string& k);
void take_pictures();
uint32_t load_snapshot();
void replay_wal(uint32_t x);

