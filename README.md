# ameyaDB
ameyaDB is a distributed KV store

# usage
run `python3 test.py` from `/ameyaDB`

# main.cpp
"Putting X on wire" means X is a thread that is reading bytes from wire
Socket is end of wire that reads and writes bytes. Socket is identified by FD.
You can read from & write to an FD at the same time!
However, you can't have 2 threads writing 2 an FD at the same time.


- **`initiate(peer_id)`**
  - establish TCP connection & send hello msg
- **`attach_listener_to_port(myPort)`**
- **`read_hello(FD)`**
  - called by acceptor. Reads hello msg & returns initiators nodeID
- **`keep_initiator_on_wire(peer_id)`**
  - initiates tcp connection to assigned peer if wire breaks
  - keeps reader on initiator's socket
- **`put_acceptor_on_wire(FD)`**
  - called when listener receives SYN packet
  - keeps reader on acceptor's socket
- **`dispatch(FD)`**
  - sends messages to the proper handler
- **`accept_forever(listener)`**
  - parking lot for  all nodes' main threads
  - creates acceptor threads and calls `put_acceptor_on_wire()` when it receives SYN packet
- **`main`**
  - restores DB from wal & connects cluster

# handlers.cpp
Parses KV to wire & sends it to walsnap

# walsnap.cpp
- **`apply_entry`**
  - write
- **`apply_r`**
  - read
- **`ensure_wal_is_open`**
- **`remove_temp_snap`**
  - remove temp snap on reboot
- **`truncate_wal`**
  - truncate wal
- **`take_pics`**
  - create snapshots
- **`load_snap`**
  - load snap into DB
- **`replay_wal`**
  - replay wal entry not covered by snap
- **`get_last_log_entry`**