#include "../headers/threads.h"
#include "../headers/globals.h"
#include <atomic>
#include <chrono>
#include <ctime>
#include <cstdio>
#include <fcntl.h>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <unistd.h>
#include <sys/timex.h>
#include <clockbound.h>


static mutex print_mutex;
static mutex relay_mutex;


static atomic<unsigned long long> msgs_sent_to_browser_count{0};
static long long life_count = 0;

static clockbound_ctx *CB_contex = nullptr;


static string incarnation_path(int node_id) {
    return "node" + to_string(node_id) + ".incarnation";
}

long long load_and_bump_incarnation(int node_id) {

    const string path = "node" + to_string(node_id) + ".incarnation";

    long long cur = 0;
    if (FILE *f = fopen(path.c_str(), "r")) {
        if (fscanf(f, "%lld", &cur) != 1) cur = 0;
        fclose(f);
    }
    const long long next = cur + 1;

    const string tmp = path + ".tmp";
    int fd = open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        const string s = to_string(next) + "\n";
        ssize_t w = write(fd, s.c_str(), s.size());
        (void) w;
        fsync(fd);
        close(fd);
        if (rename(tmp.c_str(), path.c_str()) == 0) {
            int dfd = open(".", O_RDONLY);
            if (dfd >= 0) { fsync(dfd); close(dfd); }
        }
    }

    my_incarnation = next;
    return next;
}
static long long phc_error_bound_us() {
    FILE *f = fopen("/sys/bus/pci/devices/0000:00:03.0/phc_error_bound", "r");
    if (!f) return -1;
    long long ns = -1;
    if (fscanf(f, "%lld", &ns) != 1) ns = -1;
    fclose(f);
    if (ns < 0) return -1;
    return (ns + 999) / 1000;   // round up; never understate the bound
}
static long long kernel_error_bound_us() {
    struct timex tx {};
    int st = adjtimex(&tx);
    if (st < 0) return -1;
    if (st == TIME_ERROR) return -1;
    if (tx.status & STA_UNSYNC) return -1;
    return tx.maxerror >= 0 ? static_cast<long long>(tx.maxerror) : -1;
}

// Fills wall_us and err_us together so they always describe the same instant.
static void sample_clock(long long &wall_us, long long &err_us) {
    if (cb_ctx) {
        clockbound_now_result now {};
        clockbound_err cb_err {};
        if (clockbound_now(cb_ctx, &now, &cb_err) == 0) {
            const long long earliest =
                static_cast<long long>(now.earliest.tv_sec) * 1000000LL + now.earliest.tv_nsec / 1000;
            const long long latest =
                static_cast<long long>(now.latest.tv_sec) * 1000000LL + now.latest.tv_nsec / 1000;
            wall_us = (earliest + latest) / 2;
            err_us  = (latest - earliest + 1) / 2;   // half-width, rounded up
            return;
        }
    }

    wall_us = chrono::duration_cast<microseconds>(system_clock::now().time_since_epoch()).count();

    err_us = phc_error_bound_us();
    if (err_us < 0) err_us = kernel_error_bound_us();
}

void init_stamping(int node_id) {
    clockbound_err cb_err {};
    cb_ctx = clockbound_open(CLOCKBOUND_SHM_DEFAULT_PATH, &cb_err);
    if (!cb_ctx)
        cerr << "[init_stamping] clockbound_open failed; falling back to "
                "sysfs/adjtimex error bounds\n";

    load_and_bump_incarnation(node_id);
}


void print(const std::string &msg) {

    // Deliberately unchanged. This is the human stream you tail in a terminal,
    // so it stays readable local time. Only the relay wire format -- which is
    // read by a machine -- carries the ordering fields.
    auto curTime = system_clock::now();
    auto curTime_ms = chrono::duration_cast<milliseconds>(curTime.time_since_epoch()) % 1000;

    time_t tt = system_clock::to_time_t(curTime);
    tm local_tm{};
    localtime_r(&tt, &local_tm);

    // t (node) (msg)
    ostringstream line;
    line << put_time(&local_tm, "%M:%S") << '.'
         << setw(3) << setfill('0') << curTime_ms.count()
         << " (node " << myNodeID << ") (" << msg << ")\n";

    lock_guard<mutex> lock(print_mutex);
    cout << line.str() << flush;
}


void send_to_relay(int fd, const std::string &msg) {

    const unsigned long long seq = node_seq.fetch_add(1, memory_order_relaxed);

    long long wall_us = 0, err_us = -1;
    sample_clock(wall_us, err_us);

    // <incarnation> <node_seq> <wall_us> <err_us> (node N) (msg)
    ostringstream line;
    line << my_incarnation << ' ' << seq << ' ' << wall_us << ' ' << err_us
         << " (node " << myNodeID << ") (" << msg << ")\n";
    const string out = line.str();

    lock_guard<mutex> lock(relay_mutex);
    ssize_t w = write(fd, out.c_str(), out.size());
    (void) w;
}