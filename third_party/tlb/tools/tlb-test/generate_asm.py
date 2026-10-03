from enum import Enum
from math import log2
from random import randint

JMP_SIZE = 512
POW_LIMIT = 31

InstrTypeEnum = Enum('InstrType', [('DIV', 1), ('MUL', 2), ('ADD', 3), ('POPCNT', 4), ('RCL', 5), ('BTR', 6), ('XCHG', 7)])

def _divRounds(rounds: int, target: int, divSize: int) -> str:
	asm = ""
	mask = (1 << divSize) - 1
	rcx = (-randint(0, 32767)) % (1 << 128)
	rcx &= (mask >> 1)
	rax = (-randint(0, 32767)) % (1 << 128)
	rax &= mask
	rdx = target

	for i in range(rounds):
		n = rcx * rax + rdx
		rdx = n >> divSize
		rax = n & mask

	asm += "\tmov $" + str(rcx) + ", %rcx\n"
	asm += "\tmov $" + str(rax) + ", %rax\n"
	asm += "\tmov $" + str(rdx) + ", %rdx\n"

	regPrefix = ("" if divSize == 16 else ("r" if divSize == 64 else "e"))
	for i in range(rounds):
		asm += "\tdiv  %" + regPrefix + "cx\n"
	return asm

def _start_for_mulRounds(rounds: int, target: int, pow_limit: int)-> int:
	target_power = int(log2(target))
	start_power = (target_power - (rounds % pow_limit)) % pow_limit
	return 2**start_power

def _mulRounds(rounds: int, target: int, init: int = -1) -> str:
	mulRounds = rounds
	asm = ""


	target_power = int(log2(target))
	remaining = target - (2**target_power)

	if init == -1:
		rdx = _start_for_mulRounds(rounds, target, POW_LIMIT)
		asm += "\tmov $" + str(rdx) + ", %rdx\n"
	else:
		rdx = init

	for i in range(mulRounds):
		asm += "\timul  $2, %rdx, %rdx\n"
		rdx *= 2
		if rdx == 2**POW_LIMIT:
			s = (2**POW_LIMIT) - 1
			asm += "\tsub  $" + hex(s) + ", %rdx\n"
			rdx -= s

	if (remaining != 0):
		asm += "\tadd  $" + str(remaining) + ", %rdx\n"
	return asm

def _addRounds(rounds: int, target: int, initial: int = -1) -> str:
	asm = ""
	step = 1

	if initial == -1:
		rdx = target - rounds
		asm += "\tmov $" + str(rdx) + ", %rdx\n"
	else:
		rdx = initial
		step = -1 if rdx > target else 1

	for i in range(rounds-1):
		rdx += step
		asm += f"\t{'add' if step == 1 else 'sub'}  $1, %edx\n"

	if (target != rdx):
		asm += f"\t{'add' if step == 1 else 'sub'}  ${abs(target - rdx)}, %edx\n"

	return asm

def create_window(name: str, instrType: InstrTypeEnum, rounds: int, target: int = JMP_SIZE):
	
	globalAsm = (
		".align 16\n"
		f".globl {name}\n"
		f"{name}:\n"
	)

	if instrType == InstrTypeEnum.DIV:
		divSize = 32
		globalAsm += _divRounds(rounds, target, divSize)
	elif instrType == InstrTypeEnum.MUL:
		globalAsm += _mulRounds(rounds, target)
	elif instrType == InstrTypeEnum.ADD:
		globalAsm += _addRounds(rounds, target)
	else:
		print("Wrong type")
		exit(1)
	
	# ===============End==========================
	globalAsm += "\taddq %rdx, (%rsp)\n"
	globalAsm += "\tret\n"
	with open(f"{name}.S", "w") as file:
		file.write(globalAsm)

def create_window_combined(name: str, div_rounds: int, mul_rounds: int, add_rounds: int, offset: int):
	jmpSize = JMP_SIZE + offset
	div_target = 0
	mul_target = 0

	# div < mul -> default mul behaviour + normal div behaviour to reach mul start
	# mul < div -> default div behaviour + reach 
	# div == mul -> default 

	globalAsm = (
		".align 16\n"
		f".globl {name}\n"
		f"{name}:\n"
	)
	# ===========================================
	divSize = 32

	mul_target = JMP_SIZE // (2 if add_rounds != 0 else 1)
	div_target = _start_for_mulRounds(mul_rounds, mul_target, POW_LIMIT)
	globalAsm += _divRounds(div_rounds, div_target, divSize)
	globalAsm += _mulRounds(mul_rounds, mul_target, div_target)
	globalAsm += _addRounds(add_rounds, jmpSize, mul_target)

	globalAsm += "\taddq %rdx, (%rsp)\n"
	globalAsm += "\tret\n"
	with open(f"{name}.S", "w") as file:
		file.write(globalAsm)

def main():
	create_window("window_call_ret", InstrTypeEnum.MUL, 15)
	# create_window_combined("window_call_ret", 2, 3, 4, 0)


if __name__ == '__main__':
	main()
