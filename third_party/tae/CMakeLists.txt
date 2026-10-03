cmake_minimum_required(VERSION 3.14)

# use clang to compile
set(CMAKE_CXX_COMPILER clang++-17)
set(CMAKE_C_COMPILER clang-17)
project(WeirdMachine LANGUAGES CXX)

# Set output directories for compiled files
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)

# Allow users to enable/disable components
option(BUILD_EXAMPLES "Build example programs" ON)

# Create the library
add_subdirectory(src)

# Conditionally build examples
if(BUILD_EXAMPLES)
    add_subdirectory(examples)
endif()

# Install headers
install(DIRECTORY include/ DESTINATION include/)
