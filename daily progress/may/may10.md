**

Process is server code.

wal.flush(wr) : in-memory → buffer

Buffer moves writes into disk every few ms



Partial Write is in Buffer when

1. half of the write is loaded from process into buffer

2. the process crashes




SIGKILL crashes process, not buffer.

Partial writes in buffer become partial writes in disk.

fsync() forces the buffer to flush everything it has into disk



reboot = machine crashed

restart = process crashed



On restart, un—ack’d writes will be in WAL so they will be replayed into DB

Client-side only knows the process order of writes by the log__idx being sent in the ack

Client-side can never know process order of un–ack’d writes

Therefore, Client-side can never construct expected state of DB




**