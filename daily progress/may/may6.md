to solve the out of order ack bug we would need a shadow node to verify the WAL ∩ snapshots are what they should be.
deploy pulls files from src.server from github, dumps them on ec2, compiles then runs them
run_server_locally compiles ∩ runs files from src/server on mac

Server sends ack after write is applied to db. If you wait for ack before sending the next write in the tcp socket, then the writes are sequential. The fix is to send all writes through the tcp socket without checking for an ack, then closing all connections at once. Server crashes if it tries to ack client that closed their side of the tcp socket. The fix is to send all writes before checking for acks, then checking for acks in a loop until you have enough.

timeval crashes local test if

There is 5 second gap between last write sent ∩ first ACK received
There is a 5 second gap between 2 ACKs


each client gets 1 worker. 1 worker processes 1 write in 1 socket @ one time. This is OK since waiting for lock is bottleneck.
The number of threads waiting on lock ≤ number of clients
local test should fail if we don't get back all ACKs