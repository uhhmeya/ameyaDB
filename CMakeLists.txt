cmake_minimum_required(VERSION 3.20)
project(ameyaDB)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_PREFIX_PATH "/opt/homebrew")

find_package(AWSSDK REQUIRED COMPONENTS core sns sqs)
file(GLOB_RECURSE SOURCES engine/src/server/*.cpp)
add_executable(ameyaDB_node ${SOURCES})
target_include_directories(ameyaDB_node PRIVATE engine/src)
target_link_libraries(ameyaDB_node ${AWSSDK_LINK_LIBRARIES})
add_executable(local_test engine/src/clients.cpp)
target_include_directories(local_test PRIVATE engine/src)
target_compile_definitions(local_test PRIVATE TESTING)