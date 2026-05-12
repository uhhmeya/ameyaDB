server_wd = src.server
client_wd = src
import paths to X.cpp are relative to X.cpp
paths defined as variables are relative to wd
local_server.wait() STOPS test.py until server is destroyed
local_clients.wait() STOPS test.py until clients.cpp stops running

.
1. client sends wr
2. server applies wr to db
3. server sends ack
4. client appends wr to ack_txt

.
1. 30 clients dump ALL 30k writes into the socket INSTANTLY
2. wait until ack__arr.size() > 15k
3. first thread to notice threshold is crossed grabs lock
4. dump ack__arr into ACK.TXT
5. make sentinel
6. server crashes
7. all sockets close server-side
8. all sockets close client-side
9. all threads exit
10. return 0