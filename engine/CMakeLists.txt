cmake_minimum_required(VERSION 3.20)
project(ameyaDB)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(ameyaDB_node
        src/main.cpp
)

target_include_directories(ameyaDB_node PRIVATE src)

