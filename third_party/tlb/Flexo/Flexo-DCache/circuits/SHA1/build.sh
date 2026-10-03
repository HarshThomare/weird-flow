#!/bin/sh

make -C circuits/SHA1/ clean && \
make -C circuits/SHA1/ && \
./compile.sh circuits/SHA1/sha1_round.ll circuits/SHA1/sha1_round-wm.ll && \
clang-17 circuits/SHA1/sha1_round-wm.ll -o circuits/SHA1/sha1_round.elf -lm -lstdc++ && \
./compile.sh circuits/SHA1/sha1_2blocks.ll circuits/SHA1/sha1_2blocks-wm.ll && \
clang-17 circuits/SHA1/sha1_2blocks-wm.ll -o circuits/SHA1/sha1_2blocks.elf -lm -lstdc++
