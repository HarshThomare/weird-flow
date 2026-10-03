#!/bin/sh

compile_alux() {
    local SIZE="$1"
		local NAME="ALU$SIZE"

		export WM_CIRCUIT_FILE=circuits/ALU/_"$NAME".v && \
		./compile.sh circuits/ALU/"$NAME".ll circuits/ALU/"$NAME"-wm.ll && \
		clang-17 circuits/ALU/"$NAME"-wm.ll -o circuits/ALU/"$NAME".elf -lm -lstdc++
}

# SIZE_VALUES="8 9 10 11 12 14 16 24 32 34 36 40"
SIZE_VALUES="8 9 10 11 12"

make -C circuits/ALU/ SIZE_VALUES="$SIZE_VALUES" clean && \
make -C circuits/ALU/ SIZE_VALUES="$SIZE_VALUES" && \
(
	for SIZE in $SIZE_VALUES; do
		compile_alux "$SIZE"
	done
)
