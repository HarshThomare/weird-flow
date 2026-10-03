#!/bin/sh

make -C circuits/Simon/ clean && \
make -C circuits/Simon/ && \
./compile.sh circuits/Simon/simon32.ll circuits/Simon/simon32-wm.ll && \
clang-17 circuits/Simon/simon32-wm.ll -o circuits/Simon/simon32.elf -lm -lstdc++
