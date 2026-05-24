#pragma once
#include <string>
#include <cstdint>

using namespace std;

struct User {
    int     userID;
    string  name;
    string  role;
};

struct Account {
    int      accID;
    uint64_t created;
    string   currency;
    string   type;
};

struct AccountOwner {
    int userID;
    int accID;
};

struct Transaction {
    int      transID;
    int      from_accID;
    int      to_accID;
    double   amount;
    uint64_t time;
    string   status;
};

struct Balance {
    int      accID;
    double   balance;
    uint64_t time;
};