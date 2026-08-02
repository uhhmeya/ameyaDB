#include "../headers/threads.h"
#include "../headers/globals.h"

#include <chrono>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>


thread_local ThreadInfo Thr;

static mutex print_mutex;

void print(const std::string &msg) {

    // get current time
    auto curTime = system_clock::now();
    auto curTime_ms = chrono::duration_cast<milliseconds>(curTime.time_since_epoch()) % 1000;

    // formats time
    time_t tt = system_clock::to_time_t(curTime);
    tm local_tm{};
    localtime_r(&tt, &local_tm);

    //t (nodeID) (type) (msg)
    ostringstream line;
    line << put_time(&local_tm, "%M:%S") << '.'
         << setw(3) << setfill('0') << curTime_ms.count()
         << " (" << myNodeID << ") (" << Thr.type() << ") (" << msg << ")\n";


    lock_guard<mutex> lock(print_mutex);
    cout << line.str() << flush;
}