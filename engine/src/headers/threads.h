#pragma once
#include <string>

void print(const std::string &msg);
void send_to_relay(int fd, const std::string &msg);
void init_stamping(int node_id);
long long load_and_bump_incarnation(int node_id);