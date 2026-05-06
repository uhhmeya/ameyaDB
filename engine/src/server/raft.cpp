#include "../headers/raft.h"
#include "../headers/globals.h"
#include <thread>
#include <chrono>
#include <cstdlib>

void start_election() {
    role = CANDIDATE;
    term++;
    vote = node_id;
}

void run_election_timer() {
    while (true) {
        int rtimer = 150 + rand() % 150;
        this_thread::sleep_for(chrono::milliseconds(rtimer));

        if (role == LEADER)
          continue;

        if (now_ms() - time_of_last_hb_received.load() >= (uint64_t)rtimer)
            start_election();
    }
}