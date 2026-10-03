# Define the library
add_library(WeirdMachine STATIC)

# compiler flags
set(compile_warnings -Wall -Wno-unused-function -Wno-unused-variable -Wno-unused-but-set-variable -Wno-missing-braces)
set(shared_compile_options "${compile_warnings}" -O2)
target_compile_options(WeirdMachine PRIVATE ${shared_compile_options})
target_compile_features(WeirdMachine PRIVATE cxx_std_20)

# Add all source files recursively
file(GLOB_RECURSE LIB_SOURCES "*.cpp")
target_sources(WeirdMachine PRIVATE ${LIB_SOURCES})
message(LIB_SOURCES="${LIB_SOURCES}")

# Specify include directories
target_include_directories(WeirdMachine PUBLIC ${CMAKE_SOURCE_DIR}/include)

# Installation instructions
install(TARGETS WeirdMachine
        LIBRARY DESTINATION lib
        ARCHIVE DESTINATION lib)
