auto flush crash causes tmp snaps
make truncated wal then atomic swap it with normal wal to avoid data loss
wal_in is old WAL that worker threads are appending writes to
wal_out is new truncated WAL that will replace old wal


a << b << c
* your writing abc to file on disk
  abc hits buffer
  buffer auto flushes to file
  do file.flush at end to flush remaining bytes to file

take_pics [ ] :

    cur_idx > idx_of_first_wr_in_prev_pic + 100

    idx_of_first_wr_in_new_snap != cur_idx

    dk' := dk  ]
    dk  = {}   ]  atomic

    prev_snap + dk' ——> new_snap

    open  snap.[idx_of_first_wr_in_new_snap].temp

        copy entries from new_snap into temp file

    rename tmp -> bin to publish

    open  new_wal  ∩  old_wal

        for write in wal_in :

            if write.idx > idx_of_first_wr_in_new_snap

                append write to wal_out

    atomic swap old_wal with new_wal to publish new_wal

    increment ∩ delete old snaps