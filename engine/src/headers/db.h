#pragma once
#include <string>
#include "wr.h"

using namespace std;

uint32_t compute_checksum(const wr& w);
string serialize_wr(const wr& w);

void apply_wr(const wr& w);
string apply_r(const std::string& k);

void take_pictures();
int load_snap();
void replay_wal(uint32_t x);

