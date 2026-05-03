snapshot.(log index at time of pic)

snap is dictionary

with dk, we can take new_snap by modifying prev_snap

when taking first snap, prev_snap is what we loaded from WAL.

1. load_snap()
2. replay WAL entries not covered by snap
3. take first pic

snapshot is loaded and WAL is replayed on boot by 1 thread.

1. terraform creates infrastructure
2. deploy script runs CPP files on ec2
3. main.cpp creates root directory /var/log/ameyaDB
4. main.cpp creates wal.log in root directory


terraform destroy wipes EBS volumes
terminating instances keeps EBS volumes