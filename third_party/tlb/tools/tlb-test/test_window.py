from enum import Enum
import os
import subprocess
import sys
import numpy as np
from tqdm import tqdm, trange
import statistics
from pathlib import Path

from generate_asm import create_window_combined

WindowLoadType = Enum('WindowLoadType', [('LOAD', 0), ('LOAD_2ND', 1)])

LOAD_TYPE = WindowLoadType.LOAD
MAX_LOADS = -1

def _compile_test(div_rounds: int, mul_rounds: int, add_rounds: int):
	# Compilation
	create_window_combined("window_call_ret", div_rounds, mul_rounds, add_rounds, 0)
	out = subprocess.run(["make", "window"], capture_output=True)
	if (out.returncode != 0):
		exit(out.returncode)

def _run_test(cpu: int, threshold: int) -> tuple[int, int, int]:
	envs = os.environ.copy()
	envs["THRESHOLD"] = str(threshold)
	out = subprocess.run(["taskset", "-c", str(cpu), "./test_window.elf"], env=envs, capture_output=True, text=True).stdout
	outs = [int(o) for o in out.split("\n")[-2].split(",")]
	# loads, loads2, cycles
	return (outs[0], outs[1], outs[2])

def _average_tuple(t: tuple[int]) -> float:
	return np.mean(t, axis=0)

RESULT_ENTRY_TYPE = tuple[tuple[float, list[int]], tuple[float, list[int]], tuple[float, list[int]]]
RESULTS = list[RESULT_ENTRY_TYPE]

def test_window(iterations:int, cpu: int, threshold: int, div_rounds: int, mul_rounds: int, add_rounds: int) -> RESULT_ENTRY_TYPE:
	_compile_test(div_rounds, mul_rounds, add_rounds)
	results = [_run_test(cpu, threshold) for _ in (range(iterations) if iterations < 2 else trange(iterations, leave=False))]
	l1, l2 , l3= zip(*results)
	# loads, loads, cycles
	return (_average_tuple(l1), list(l1)), (_average_tuple(l2), list(l2)), (_average_tuple(l3), list(l3))

def tune(cpu: int, threshold: int, iterations: int, target_loads: int):
	load_type = WindowLoadType.LOAD

	rounds = [0, 0, 0]
	rounds_str = ["DIV", "MUL", "ADD"]
	"""
	Find best value for `rounds` by incrementing with `stepsize` until number of divs matches without transient window.
	Then finetune this value to the threshold where it changes
	"""
	for i in range(len(rounds)):
		print("Adjusting", rounds_str[i], "rounds")
		load_value = test_window(iterations, cpu, threshold, rounds[0], rounds[1], rounds[2])[load_type.value][0]
		prev_loads = load_value
		stepsize = 5
		prev_stepsize = stepsize
		while (True):
			print(rounds, '->', load_value)
			# when gone over found point -> reduce stepsize
			if (prev_loads >= target_loads) != (load_value >= target_loads):
				prev_stepsize = stepsize
				stepsize = max(stepsize//2, 1)
			# when too low increase rounds
			if load_value < target_loads:
				rounds[i] += stepsize
				# when gone below limit, but one step before it was too high -> finish
				if prev_loads >= target_loads and prev_stepsize == 1:
					break
			# when gone too high -> reduce rounds
			if load_value >= target_loads:
				# when previous one step away was less than target -> finish
				if prev_loads < target_loads and prev_stepsize == 1:
					rounds[i] -= 1
					break
				rounds[i] = max(0, rounds[i] - stepsize)
			prev_loads = load_value
			load_value = test_window(iterations, cpu, threshold, rounds[0], rounds[1], rounds[2])[load_type.value][0]
	rounds[-1] += 1
	print(rounds)

def get_max_loads_possible(cpu: int, threshold: int, load_type: WindowLoadType):
	value = test_window(2, cpu, threshold, 1000, 0, 0)[load_type.value][0]
	if int(value) == value:
		return int(value)
	else:
		return int(value) + 1
	
# MIN_ROUNDS = [30, 100, 200]
MIN_ROUNDS = [30, 100, 0]
ROUNDS_STR = ["DIV", "MUL", "ADD"]

def _load_data(cpu: int, threshold: int, iterations: int, i: int, load_type: WindowLoadType, suffix: str)-> tuple[list[list[int]],list[list[int]]]:
	Path("./data").mkdir(exist_ok=True)
	round_str = ROUNDS_STR[i]
	name = f"data/{cpu}-{threshold}-{iterations}-{round_str}_{load_type.name}_{suffix}"
	filename = name +".npy"
	if os.path.exists(filename):
		results: RESULTS = list(np.load(filename, allow_pickle=True))
	else:
		results: RESULTS = []
	rounds = [0, 0, 0]
	rounds[i] = len(results)
	print("Measure", ROUNDS_STR[i], "rounds")
	try:
		for _ in trange(len(results), MIN_ROUNDS[i]):
			rounds[i] += 1
			results.append(test_window(iterations, cpu, threshold, rounds[0], rounds[1], rounds[2]))
		for _ in trange(rounds[i], 1000):
			if results[-1][load_type.value][0] > MAX_LOADS-1 or results[-2][load_type.value][0] > MAX_LOADS-1:
				break
			rounds[i] += 1
			results.append(test_window(iterations, cpu, threshold, rounds[0], rounds[1], rounds[2]))
	except KeyboardInterrupt:
		np.save(filename, np.array(results, dtype=object))
		exit(1)

	np.save(filename, np.array(results, dtype=object))
	np.savetxt(name + "_loads.csv", [e[load_type.value][1] for e in results], delimiter=',', fmt='%d')
	np.savetxt(name + "_cycles.csv", [e[2][1] for e in results], delimiter=',', fmt='%d')
	outs: tuple[list[list[int]],list[list[int]]] = [e[load_type.value][1] for e in results],[e[2][1] for e in results]
	return outs

def main():
	if (len(sys.argv) < 5):
		print("Give more arguments:")
		print("cmd ... CPU THRESHOLD ITERATIONS SUFFIX (NR_TARGET_LOADS)")
		exit(1)
	cpu = int(sys.argv[1])
	threshold = int(sys.argv[2])
	iterations = int(sys.argv[3])
	suffix = sys.argv[4]
	if (len(sys.argv) > 5):
		target_loads = int(sys.argv[5])
		tune(cpu, threshold, iterations, target_loads)
	else:
		MAX_LOADS = get_max_loads_possible(cpu, threshold, LOAD_TYPE)
		print("Got maximum loads", MAX_LOADS)
		for i in range(len(ROUNDS_STR)):
			results = _load_data(cpu, threshold, iterations, i, LOAD_TYPE, suffix)

if __name__ == '__main__':
	main()
