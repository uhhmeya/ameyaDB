server process that isn't crashed at end of test becomes zombie
kill $(lsof -t -i:8080) = terminates zombie

cleanup() deletes all snapshots, then wal, then client_wal, then sentinel
cleanup() is run at START of every test
pid is unique number assigned to every process

Build = Compile
Building script creates
Popen(binary of script) = runs script

Building script creates binary of script
cwd = working directory
Path is relative to process's cwd on runtime
Path is relative to cpp file location on compile time

Popen(binary of script, cwd)

Popen(binary of server script, cwd = src.server)
* creates server
  Popen(binary of client script, cwd = src)
* creates clients

clients create ACK & sentinel so the paths should be "/output/X"
server creates WAL & snaps so path should be "../output/X"

