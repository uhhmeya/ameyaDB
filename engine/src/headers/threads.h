#pragma once
#include <string>

void print(const std::string &msg);
void send_to_relay(const std::string &msg);
long long get_and_update_life_count(int node_id);
void connect_to_CB();