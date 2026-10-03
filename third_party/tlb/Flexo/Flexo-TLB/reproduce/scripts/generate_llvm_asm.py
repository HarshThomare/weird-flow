#!/bin/python3

import sys
from generate_asm import _divRounds, _mulRounds

def main():
	if len(sys.argv) < 4:
		print("USAGE:")
		print(f"\t{sys.argv[0]} MUL_ROUNDS JMP_SIZE MUL_SIZE")
	mulRounds = int(sys.argv[1])
	jmpSize = int(sys.argv[2])
	mulSize = int(sys.argv[3])

	asm = _mulRounds(mulRounds, jmpSize, mulSize)
	# asm = _divRounds(mulRounds, jmpSize, mulSize)
	print(asm)


if __name__ == '__main__':
	main()
