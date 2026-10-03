from enum import Enum
from math import log2
from os import environ
from random import randint

JMP_SIZE = 512

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

	asm += "    mov $" + str(rcx) + ", %rcx\n"
	asm += "    mov $" + str(rax) + ", %rax\n"
	asm += "    mov $" + str(rdx) + ", %rdx\n"

	regPrefix = ("" if divSize == 16 else ("r" if divSize == 64 else "e"))
	for i in range(rounds):
		asm += "    div  %" + regPrefix + "cx\n"
	return asm

def _start_for_mulRounds(rounds: int, target: int, pow_limit: int)-> int:
	target_power = int(log2(target))
	start_power = (target_power - (rounds % pow_limit)) % pow_limit
	return 2**start_power

def _mulRounds(rounds: int, target: int, mulSize: int, init: int = -1) -> str:
	mulRounds = rounds
	asm = ""

	pow_limit = mulSize-1
	limit = 1 << pow_limit
	backstep = limit - 1

	target_power = int(log2(target))
	remaining = target - (2**target_power)
	rdx_str = ("" if mulSize == 16 else ("r" if mulSize == 64 else "e")) + "dx"

	if init == -1:
		rdx = _start_for_mulRounds(rounds, target, pow_limit)
		asm += "    mov $" + str(rdx) + ", %rdx\n"
	else:
		rdx = init

	for i in range(mulRounds):
		asm += "    imul  $2, %" + rdx_str + ", %" + rdx_str + "\n"
		rdx *= 2
		if rdx >= limit:
			asm += "    sub  $" + hex(backstep) + ", %" + rdx_str + "\n"
			rdx -= backstep

	if (remaining != 0):
		asm += "    add  $" + str(remaining) + ", %" + rdx_str + "\n"
	return asm

def _addRounds(rounds: int, target: int, initial: int = -1) -> str:
	asm = ""
	step = 1

	if initial == -1:
		rdx = target - rounds
		asm += "    mov $" + str(rdx) + ", %rdx\n"
	else:
		rdx = initial
		step = -1 if rdx > target else 1

	for i in range(rounds-1):
		rdx += step
		asm += f"    {'add' if step == 1 else 'sub'}  $1, %edx\n"

	if (target != rdx):
		asm += f"    {'add' if step == 1 else 'sub'}  ${abs(target - rdx)}, %edx\n"

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
		mulSize = 32
		globalAsm += _mulRounds(rounds, target, mulSize)
	elif instrType == InstrTypeEnum.ADD:
		globalAsm += _addRounds(rounds, target)
	else:
		print("Wrong type")
		exit(1)
	
	# ===============End==========================
	globalAsm += "    addq %rdx, (%rsp)\n"
	globalAsm += "    ret\n"
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
	mulSize = 32

	mul_target = JMP_SIZE // (2 if add_rounds != 0 else 1)
	div_target = _start_for_mulRounds(mul_rounds, mul_target, mulSize-1)
	globalAsm += _divRounds(div_rounds, div_target, divSize)
	globalAsm += _mulRounds(mul_rounds, mul_target, mulSize, div_target)
	globalAsm += _addRounds(add_rounds, jmpSize, mul_target)

	globalAsm += "    addq %rdx, (%rsp)\n"
	globalAsm += "    ret\n"
	with open(f"{name}.S", "w") as file:
		file.write(globalAsm)


def create_window_ret(instrType: InstrTypeEnum, rounds: int) -> None:
	globalAsm = "\"mov $5, %ebx\\n"
	globalAsm += "mov $1, %eax\\n"
	for i in range(rounds):
		if instrType == InstrTypeEnum.MUL:
			# 2 byte per instruction
			# 2uops, 4 delay
			globalAsm += "mul %ebx\\n"
		elif instrType == InstrTypeEnum.ADD:
			# 2 byte per instruction
			# 1uops, .2 delay
			globalAsm += "inc %eax\\n"
		elif instrType == InstrTypeEnum.POPCNT:
			# 4 byte per instruction
			# 1uops, 3 delay
			globalAsm += "popcnt %eax, %ebx\\n"
			# 2 byte per instruction
			# 1uops, 1 delay
			globalAsm += "add %ebx, %eax\\n"
		elif instrType == InstrTypeEnum.RCL:
			# 2 byte per instruction
			# 1/16uops, 2/14 delay
			globalAsm += "rcl $1, %eax\\n"
		elif instrType == InstrTypeEnum.BTR:
			# 4 byte per instruction
			# 1uops, 1 delay
			globalAsm += "btr $2, %eax\\n"
		elif instrType == InstrTypeEnum.XCHG:
			# 1 byte per instruction
			# 3uops, .67 delay
			globalAsm += "xchg %eax, %ebx\\n"
		else:
			print("Wrong type")
			exit(1)
	# 2 byte per instruction
	globalAsm += "div %ebx\\n"
	globalAsm += "\""
	with open("window.inc", "w") as file:
		file.write(globalAsm)


def main():
	create_window("mod_ret_addr", InstrTypeEnum.MUL, 15)
	# create_window("mod_ret_addr", InstrTypeEnum.DIV, 5)
	# create_window_combined("mod_ret_addr", 2, 3, 5, 0)
	# create_window_combined("window_call_ret", 2, 3, 4, 0)


if __name__ == '__main__':
	main()
