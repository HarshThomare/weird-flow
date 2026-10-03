#!/bin/sh

make -C circuits/arithmetic/ clean && \
make -C circuits/arithmetic/ && \
./compile.sh circuits/arithmetic/adder.ll circuits/arithmetic/adder-wm.ll && \
clang-17 circuits/arithmetic/adder-wm.ll -o circuits/arithmetic/adder.elf -lm -lstdc++ && \
./compile.sh circuits/arithmetic/mul.ll circuits/arithmetic/mul-wm.ll && \
clang-17 circuits/arithmetic/mul-wm.ll -o circuits/arithmetic/mul.elf -lm -lstdc++
