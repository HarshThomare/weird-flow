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
export WR_HIT_THRESHOLD=121 DUAL_WM_MAX_INPUT=3 RET_WM_MUL_ROUNDS=17 RET_WM_MUL_SIZE=32
opt-17 -load-pass-plugin ./build/lib/libFlexo.so -passes="create-WMs" "$1" -S -o "$output"
