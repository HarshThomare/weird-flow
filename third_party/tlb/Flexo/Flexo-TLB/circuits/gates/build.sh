#!/bin/sh

make -C circuits/gates/ clean && \
make -C circuits/gates/ && \
./compile.sh circuits/gates/test.ll circuits/gates/test-wm.ll && \
clang-17 circuits/gates/test-wm.ll -o circuits/gates/test.elf -lm -lstdc++
