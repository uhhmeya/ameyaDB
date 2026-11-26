cmake_minimum_required(VERSION 3.20)
project(ameyaDB CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

file(GLOB_RECURSE ALL_SOURCES CONFIGURE_DEPENDS "src/*.cpp")

add_library(ide_index OBJECT ${ALL_SOURCES})
target_include_directories(ide_index PRIVATE src/headers)