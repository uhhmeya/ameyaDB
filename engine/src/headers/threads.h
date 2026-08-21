#pragma once
#include <string>

void print(const std::string &msg);
void send_to_relay(int fd, const std::string &msg);
long long get_and_update_life_count(int node_id);
long long load_and_bump_incarnation(int node_id);
static void connect_to_CB();