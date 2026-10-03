#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: compile.sh [input file] [output file]"
    exit 1
fi

if [ -z "$2" ]; then
    output="output.ll"
else
    output="$2"
fi

# Config and run the Flexo compiler
export RET_WM_DIV_ROUNDS=12 WR_HIT_THRESHOLD=400 RET_WM_DIV_SIZE=64 DUAL_WM_MAX_INPUT=4
opt-17 -load-pass-plugin ./build/lib/libFlexo.so -passes="create-WMs" "$1" -S -o "$output"
