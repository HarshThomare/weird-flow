#!/bin/bash

# install the dependencies if "--install-dep" is provided as the
# first command line argument
if [ "$1" = "--install-dep" ]; then
    echo "Installing dependencies..."
    # install cmake, ninja, python3, and LLVM 17
    sudo apt update
    sudo apt install -y cmake ninja-build python3
    wget https://apt.llvm.org/llvm.sh
    chmod +x llvm.sh
    sudo ./llvm.sh 17
    rm llvm.sh
fi

# function to ensure a directory exists
ensure_dir() {
    local dir="$1"
    if ! test -d "$dir"; then
        mkdir -p "$dir"
    fi
}

# create a build dir if not exist
ensure_dir "./build"

# weird programs to be built
EXAMPLES=("simon" "aes" "search")

# function to build and copy weird programs with different number
# of reruns (for majority voting)
build_and_copy() {
    local rerun="$1"

    # create the output directory
    ensure_dir "./build/rerun${rerun}"

    # build the code
    cmake -DRERUN=$rerun -G Ninja -B build -S .
    ninja -C build

    # move executables to the output directory
    for item in "${EXAMPLES[@]}"; do
        mv "./build/bin/${item}.elf" "./build/rerun${rerun}/"
    done
}

# build weird programs without majority voting
build_and_copy 1
# weird programs with 2-out-of-3 majority voting
build_and_copy 3
