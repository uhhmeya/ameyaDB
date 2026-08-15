#pragma once
#include <string>


class ThreadInfo {

    public:
        void set_type(const std::string &type) { type_ = type; }
        const std::string &type() const { return type_; }

    private:
        std::string type_ = "?";
};

extern thread_local ThreadInfo Thr;

void print(const std::string &msg);
void send_to_relay(int fd, const std::string &msg);