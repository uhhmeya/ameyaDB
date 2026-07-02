# ameyaDB
ameyaDB is a distributed KV store

# usage
run `python3 test.py` from `/ameyaDB`

# Dirty Key Race Condition in take_pics()
A snapshot is the state of the DB at a snap index
The state of the DB is copied into a snapshot under a lock

A snapshot captures the DB state at a log index called the snap index
Holding the DB lock while dumping the DB into a snapshot prevents capturing a partial state
log index increments within the db lock.
Meaning, the log index can't advance during the dump.
Therefore, snapshot is taken when we grab the DB lock

key is dirty if it was updated after snapshot
if we take the snapshot after another thread updates the DB but before
the thread can mark a key dirty, then a fresh key is incorrectly marked dirty.
This results in unnecessarily replaying an entry when constructing the next snap
This is not a correctness issue, with negligible performance impact
The fix is a bit complex, so I will just document this as a tradeoff





