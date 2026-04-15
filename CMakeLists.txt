cmake_minimum_required(VERSION 3.20)
project(ameyaDB)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_PREFIX_PATH "/opt/homebrew")

find_package(AWSSDK REQUIRED COMPONENTS core sns sqs)

add_executable(ameyaDB_node
        engine/src/main.cpp
        engine/src/wal.cpp
        engine/src/store.cpp
        engine/src/replication.cpp
        engine/src/protocol.cpp
        engine/src/handlers.cpp
)

target_include_directories(ameyaDB_node PRIVATE engine/src)
target_link_libraries(ameyaDB_node ${AWSSDK_LINK_LIBRARIES})