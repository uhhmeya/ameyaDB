#pragma once
#include <string>
#include <optional>
#include <utility>

bool read_tcp(int client_fd, void* buf, size_t n);
std::optional<std::pair<std::string,std::string>> read_kv(int client_fd);
std::optional<std::string> read_k(int client_fd);