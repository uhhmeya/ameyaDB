#pragma once
#include <string>
#include "wr.h"

using namespace std;

uint32_t compute_checksum(const wr& w);
string serialize_wr(const wr& w);

void apply_wr(const wr& w);
std::string apply_r(const std::string& k);

void take_pictures();
uint32_t load_snapshot();
void replay_wal(uint32_t x);

