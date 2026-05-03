
log_idx is set to 0 on boot
tcp writes & sqs writes get assigned log_idx 1,2,3

# <span style="color:rgb(0, 176, 240)">D</span><span style="color:rgb(0, 176, 240)">OUBLE CRASH BUG</span>
1. log_idx = 733
2. crash
3. snap.700 is snap with largest log_idx_of_last_entry
4. snap.700 copied into DB
5. log_idx_of_last_entry_in_latest_snap := 700
6. replay_wal() discards writes 1 ⟶ 700
7. replay_wal() replays writes 700 ⟶ 733
8. main() creates listener
9. new writes get assigned log_idx 1,2,3
10. WAL stores 2 entries with log_idx=1, log_idx=2, etc.
11. log_idx = 111
12. crash
13. snap.700 is still snap with largest log_idx_of_last_entry
14. replay_wal() discards writes 1 ⟶ 700
	1. this includes pre-CRASH writes before step 1 and post-CRASH writes created on step 9-10
15. replay_wal() replays writes 700 ⟶ 733

data loss : last 111 writes not in DB or WAL
The fix is to set log_idx to the last write replayed in replay_wal()
This avoids creating second copy of WAL writes at low indexes which is the main cause of this bug


1. snap.100 is loaded & WAL is empty
	1. log_idx_of_last_entry_in_latest_snap := 100
	2. getline() returns false ; while loop is skipped
	3. main() attaches listener

2. no prev snap found & WAL is empty
	 1. log_idx_of_last_entry_in_latest_snap := 0
	 2. getline() returns false ; while loop is skipped
	 3. main() attaches listener

3. snap.100 is loaded & WAL has new entries
	1.  log_idx_of_last_entry_in_latest_snap := 100
	2. log_idx := log_idx_of_last_write_replayed

For the first case, new writes would create a second set of entries with the same log indexes, creating the double crash bug described earlier. This is why log idx must be set to log idx of last write in latest snap in replay_wal() then set to log idx of last write replayed to cover all of the cases.


