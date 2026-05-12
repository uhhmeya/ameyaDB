reboot loses dk
prev_snap becomes db before crash
so keys lost in dk are no longer dirty

client does not know order that server processes req

client A sends k→v1
client B sends k→v2 at same time
client-side has no idea what get(k) should return

server should ACK with idx

client-side can't construct expected state properly if server crashes before sending ACK, this is a correctness tradeoff.

server crashes before sending ack
1. idx++
2. write in wal
3. crash

^ expected state cannot access this write. (tradeOff)

committed writes go to global.wal
writes sent by thread go to thread_local.wal

sentinel is empty file that sends a signal
when python see's sentinel, it crashes server


clients spam writes
global_wal.size() > min_acks
dump global_wal to global_wal.json
script see's sentinel
script crashes server
client threads exit





