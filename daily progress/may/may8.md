prev_snap={}
socket : k1→v1 [101 times]
wal=(0,1,2,..,101 k1→v1)
db=(k1→v1)
dk={k1}

idx=101
socket : k1→v2
idx=102
* idx_during_snap=102
  wal=(102 k1→v2)
* dk={} dk'={k1}
* lock db
* snap.102=(k1→v1)
* delete wr0→102 in wal
  db=(k1→v2)
  dk={k1}
  ack k1→v2 client
  <span style="color:rgb(192, 0, 0)"># <span style="color:rgb(192, 0, 0)">CRASH</span></span>
  db=(k1→v1)
  idx_during_latest_snap=102
  k1→v2 data loss

wr5 in wal
* idx_during_snap=5
* dk={} dk'={k4}
* snap.5={wr4}
* delete wr0→5
  dk={k5}
  ack wr5 sender
  <span style="color:rgb(192, 0, 0)"># <span style="color:rgb(192, 0, 0)">CRASH</span></span>
  wr5 lost!


