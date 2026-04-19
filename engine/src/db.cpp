#include "headers/db.h"
#include "headers/wr.h"
#include "headers/globals.h"
#include <fstream>
#include <mutex>
#include <shared_mutex>

using namespace std;

void apply_wr(const wr& w) {
    static ofstream wal("/var/log/ameyaDB/wal.log", ios::app);
    static mutex wal_mutex;

    string str_wr = serialize_wr(w);

    {
        lock_guard lock(wal_mutex);
        wal << str_wr;
        wal.flush();
    }

    {
        unique_lock lock(db_mutex);
        db[w.k] = w.v;
    }
}

string apply_r(const string& k) {
    shared_lock lock(db_mutex);
    auto it = db.find(k);
    return it != db.end() ? it->second : "";
}