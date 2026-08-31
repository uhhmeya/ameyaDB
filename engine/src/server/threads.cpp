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
// libclockbound exports plain C symbols, but /usr/include/clockbound.h has no
// `#ifdef __cplusplus / extern "C"` guard of its own. Without this wrapper the
// C++ compiler mangles the names (clockbound_open(clockbound_err*)) and the
// linker cannot match them against the unmangled symbols in the .so.
extern "C" {
#include <clockbound.h>
}

static mutex print_mutex;
static mutex relay_mutex;

static atomic<unsigned long long> msgs_sent_to_browser_count{0};
static long long life_count = 0;

// reference to connection with CB
// CB is how we get accurate time
static clockbound_ctx *cb_ctx = nullptr;

// utils
static long long read_life_count(const string &path) {
    long long cur = 0;
    if (FILE *f = fopen(path.c_str(), "r")) {
        if (fscanf(f, "%lld", &cur) != 1) {
            print("[life] WARNING: " + path + " exists but could not be parsed; resetting to 0");
            cur = 0;
        }
        fclose(f);
    } else {
        print("[life] no " + path + " found (expected on first boot); starting at 0");
    }
    return cur;
}
static void save_life_count(const string &path, long long value) {
    const string tmp = path + ".tmp";
    int fd = open(tmp.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        print("[life] WARNING: could not open " + tmp + " for writing");
        return;
    }

    const string s = to_string(value) + "\n";
    ssize_t w = write(fd, s.c_str(), s.size());
    (void) w;
    fsync(fd);
    close(fd);

    if (rename(tmp.c_str(), path.c_str()) == 0) {
        int dfd = open(".", O_RDONLY);
        if (dfd >= 0) { fsync(dfd); close(dfd); }
    }
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

long long get_and_update_life_count(int node_id) {

    const string life_path = "n" + to_string(node_id) + "_.life";
    const long long prev_life = read_life_count(life_path);
    const long long this_life = prev_life + 1;

    save_life_count(life_path, this_life);

    life_count = this_life; // file scope variable
    return this_life;
}
static void get_cur_time(long long &wall_us, long long &err_us) {
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

// The clockbound build installed on this AMI declares
//     clockbound_ctx* clockbound_open(clockbound_err *err);
// i.e. one argument, no shm path -- the daemon's socket location is compiled
// into the library. Passing CLOCKBOUND_SHM_DEFAULT_PATH is a newer API.
void connect_to_CB() {
    clockbound_err cb_err {};
    cb_ctx = clockbound_open(&cb_err);
    if (!cb_ctx)
        cerr << "[connect_to_CB] clockbound_open failed; falling back to "
                "sysfs/adjtimex error bounds\n";
}

void print(const std::string &msg) {

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

    lock_guard lock(print_mutex);
    cout << line.str() << flush;
}

static string json_escape(const string &s) {
    string out;
    out.reserve(s.size() + 8);
    for (unsigned char c : s) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n";  break;
            case '\r': out += "\\r";  break;
            case '\t': out += "\\t";  break;
            default:
                if (c < 0x20) {
                    char buf[7];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += static_cast<char>(c);
                }
        }
    }
    return out;
}


// {"node":1,"life":3,"seq":42,"wall_us":172495512345,"err_us":12,"type":"wire","msg":"1 3 up"}
void send_to_relay(const std::string &type, const std::string &msg) {

    const int fd = relay_fd.load();
    if (fd < 0) return;

    const unsigned long long seq = msgs_sent_to_browser_count.fetch_add(1, memory_order_relaxed);

    long long wall_us = 0, err_us = -1;
    get_cur_time(wall_us, err_us);

    ostringstream line;
    line << '{'
         << "\"node\":"    << myNodeID         << ','
         << "\"life\":"    << life_count       << ','
         << "\"seq\":"     << seq              << ','
         << "\"wall_us\":" << wall_us          << ','
         << "\"err_us\":"  << err_us           << ','
         << "\"type\":\""  << type             << "\","
         << "\"msg\":\""   << json_escape(msg) << '"'
         << "}\n";
    const string out = line.str();

    lock_guard lock(relay_mutex);
    ssize_t w = write(fd, out.c_str(), out.size());
    (void) w;
}

void send_to_relay(const std::string &msg) {
    send_to_relay("stat", msg);
}