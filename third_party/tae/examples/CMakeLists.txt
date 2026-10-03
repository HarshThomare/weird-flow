set(EXAMPLES
    gates
    aes
    simon
    search
)

set(compile_warnings -Wall -Wno-unused-function -Wno-unused-variable -Wno-unused-but-set-variable -Wno-missing-braces)
set(shared_compile_options "${compile_warnings}" -O2)
set(RERUN 1 CACHE STRING "Number of reruns for majority voting")

foreach(example ${EXAMPLES})
    add_executable(${example}.elf ${example}.cpp)
    target_link_libraries(${example}.elf PRIVATE WeirdMachine)
    target_include_directories(${example}.elf PRIVATE ${CMAKE_SOURCE_DIR}/include)
    target_compile_options(${example}.elf PRIVATE ${shared_compile_options})
    target_compile_features(${example}.elf PRIVATE cxx_std_20)
    target_compile_definitions(${example}.elf PRIVATE RERUN=${RERUN})
endforeach()
