cmake_minimum_required(VERSION 3.20)
project(ameyaDB CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The only reason this file exists: generate compile_commands.json for clangd.
# Actual building/testing still happens via test.py + g++, not via
# `cmake --build`. See test.py for what's actually compiled into which binary.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Every .cpp under src/, picked up automatically — no more editing this file
# when you add or remove one. CONFIGURE_DEPENDS makes CMake notice when the
# file set changes and re-glob on the next `cmake --build`, but since you
# never run that, that auto-trigger won't fire on its own for you. Still
# rerun `cmake -S . -B build` after adding/removing a file (same as the old
# note said), just without hand-editing a file list to do it.
file(GLOB_RECURSE ALL_SOURCES CONFIGURE_DEPENDS "src/*.cpp")

add_library(ide_index OBJECT ${ALL_SOURCES})
target_include_directories(ide_index PRIVATE src/headers)