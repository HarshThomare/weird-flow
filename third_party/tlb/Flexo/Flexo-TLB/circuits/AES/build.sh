#!/bin/sh

make -C circuits/AES/ clean && \
make -C circuits/AES/ && \
./compile.sh circuits/AES/aes_round.ll circuits/AES/aes_round-wm.ll && \
clang-17 circuits/AES/aes_round-wm.ll -o circuits/AES/aes_round.elf -lm -lstdc++ && \
./compile.sh circuits/AES/aes_block.ll circuits/AES/aes_block-wm.ll && \
clang-17 circuits/AES/aes_block-wm.ll -o circuits/AES/aes_block.elf -lm -lstdc++
