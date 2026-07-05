cmake_minimum_required(VERSION 3.20)
project(ameyaDB CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The only reason this file exists: generate compile_commands.json for clangd.
# Actual building/testing still happens via test.py + g++, not via
# `cmake --build`. Rerun `cmake -S . -B build` whenever you add/remove files.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# --- server: mirrors test.py's g++ call for SERVER_EXEC_PATH -------------
# NOTE: test.py does NOT currently compile raft.cpp into the server binary.
# Mirrored that here. If that's unintentional, add src/server/raft.cpp to
# this list AND to test.py's g++ call.
add_executable(server
        src/server/main.cpp
        src/server/handlers.cpp
        src/server/walsnap.cpp
)
target_include_directories(server PRIVATE src/headers)

# --- client: mirrors test.py's g++ call for CLIENT_EXEC_PATH -------------
add_executable(client
        src/clients.cpp
)
target_include_directories(client PRIVATE src/headers)

# --- raft.cpp: not part of test.py's build yet, but indexed here anyway --
# so clangd gives you full diagnostics/autocomplete while you work on it.
# This target is never linked into anything and cmake --build is never
# expected to be run, so this is purely for IDE purposes.
add_library(raft_ide_only OBJECT src/server/raft.cpp)
target_include_directories(raft_ide_only PRIVATE src/headers)