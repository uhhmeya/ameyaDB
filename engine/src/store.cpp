#include "headers/store.h"
#include "headers/globals.h"

using namespace std;

void apply_write(const wr& w) {
    unique_lock lock(store_mutex);
    store[w.k] = w.v;
}

string apply_read(const string& k) {
    shared_lock lock(store_mutex);
    auto it = store.find(k);
    return it != store.end() ? it->second : "";
}