#!/bin/sh

make -C circuits/SHA1/ clean && \
make -C circuits/SHA1/ && \
./compile.sh circuits/SHA1/sha1_round_composed.ll circuits/SHA1/sha1_round-wm_composed.ll && \
clang-17 circuits/SHA1/sha1_round-wm_composed.ll -o circuits/SHA1/sha1_round_composed.elf -lm -lstdc++ && \
./compile.sh circuits/SHA1/sha1_2blocks_composed.ll circuits/SHA1/sha1_2blocks-wm_composed.ll && \
clang-17 circuits/SHA1/sha1_2blocks-wm_composed.ll -o circuits/SHA1/sha1_2blocks_composed.elf -lm -lstdc++
