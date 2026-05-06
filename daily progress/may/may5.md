./test -DTEST
if_def runs code only during test
if_n_def skips code only during test
/var/log/ameyaDB is where ec2 stores snaps & wal

if ___ def : runs during test if ___ n ___ def : skips during test dk shared by snap ∩ bthread ∩ all workers since tmp snaps only need to be deleted after crash, they should be deleted in main()

## basic crash test

keep track of all writes the local-test script sends to db use writes to make a hashmap representing expected state of db verify actual db matches expected db reboot node, and verify db was correctly restored

client opens tcp connection. server closes its end of the tcp connection after sending the ack. client closes its end of the tcp connection after it recieves the ack. client constructs expected db based on order that ack was recieved.

## out of order ACK bug

1. client 2 sends k5 → v6
2. client 3 sends k5 → v7
3. server applies k5 → v6 then k5 → v7
4. client 3 gets ack before client 2 because of network delays

→ exp = { k5 → v6 } actual = { k5 → v7 }

to solve the out of order ack bug we would need a shadow node to verify the WAL ∩ snapshots are what they should be. deploy pulls files from src.server from github, dumps them on ec2, compiles then runs them run_server_locally compiles ∩ runs files from src/server on mac

