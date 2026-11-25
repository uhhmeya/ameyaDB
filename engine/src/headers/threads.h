#pragma once
#include <string>

void print(const std::string &msg);
void send_to_relay(const std::string &type, const std::string &msg);
void note(const std::string &type, const std::string &msg);
void drain_notes_4ever();
unsigned long long get_notes_lost();
long long get_and_update_life_count(int node_id);
void connect_to_CB();