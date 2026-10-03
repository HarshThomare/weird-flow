"""Utility functions and classes"""

import statistics
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List, Tuple


def short_filename(filename: str) -> str:
    """Return the short filename of a file"""
    return filename[filename.rfind("/") + 1 : filename.rfind(".")]


def csv_to_dict(filename: str) -> Dict[str, List[int | float]]:
    """
    Load a csv file and convert it to a dictionary.
    The first column is treated as the dict key, and the other
    columns are stored as list[int | float] in the dict
    """
    with open(filename, "r", encoding="utf-8") as infile:
        lines = infile.readlines()[1:]

    output = {}
    for line in lines:
        data = line.split(",")
        if len(data) <= 1:
            continue

        nums = [(float(n) if "." in n else int(n)) for n in data[1:]]
        output[data[0]] = nums

    return output


def dict_to_csv(data: Dict[str, List[int | float]], filename: str, header: str = ""):
    """
    Save a dictionary to a csv file.
    The key of the dictionary is written to the first column, and the value,
    a list of int or float, is stored in the other columns.
    """
    output = header + "\n"

    for k, v in data.items():
        output += k + ","
        output += ",".join([(str(n) if isinstance(n, int) else f"{n:.2f}") for n in v])
        output += "\n"

    with open(filename, "w", encoding="utf-8") as ofile:
        ofile.write(output)


def parse_output(output: str) -> List[Tuple[str, float, float]]:
    """Parse execution result and return accuracy and time usage"""
    lines = output.splitlines()
    results = []

    i = 0
    while i < len(lines) - 2:
        name_beg = lines[i].find("=== ")
        if name_beg == -1:
            i += 1
            continue

        # parse the output of a gate, such as:
        # === AND gate ===
        # Accuracy: 95.11000%, Error detected: 4.81000%, Undetected error: 0.08000%
        # Time usage: 0.896 (us)
        # over 10000 iterations.
        name_end = lines[i].find(" ===", name_beg)
        assert name_end != -1, "Invalid output from a WM:\n" + output
        name = lines[i][name_beg + 4 : name_end]

        beg = lines[i + 1].find("= (")
        beg = beg + 3 if beg != -1 else lines[i + 1].find(": ") + 2
        acc = float(lines[i + 1][beg : lines[i + 1].find("%")])
        sec = float(
            lines[i + 2][lines[i + 2].find(": ") + 2 : lines[i + 2].find("(us)")]
        )

        results.append((name, acc, sec))
        i += 3

    assert len(results) > 0, "Invalid output from a WM:\n" + output
    return results


def run_program(
    program: str, iters: int, timeout: int | float = -1
) -> List[Tuple[str, float, float]]:
    """
    Measure the accuracy and runtime of a weird program.
    This function executes a weird program for `iters` times to measure the
    accuracy and runtime.
    When timeout is -1, there is no timeout when running the weird program.
    The return value is a tuple of two floats, (accuracy (%), runtime (us)).
    """
    if timeout == 0:
        return [("", 0.0, 0.0)]

    cmd = [program, "-t", str(iters)]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        check=False,
        timeout=(timeout if timeout != -1 else None),
    )
    return parse_output(proc.stdout.decode())


def median_result(filename: str, columns: int) -> Dict[str, List[Tuple[float]]]:
    """
    Read a csv file of floating numbers and output the median value for each column.
    The first column is ignored, and the second column is the name for the gate.
    The output is a dictionary with the gate name as the key and a list of (median,
    mean) tuples for each column as the value.
    """
    with open(filename, "r", encoding="utf-8") as infile:
        lines = infile.readlines()[1:]

    # convert csv data to floats
    results = defaultdict(lambda: [[] for _ in range(columns)])
    for line in lines:
        tokens = line.split(",")
        if len(tokens) < columns + 2:
            continue
        gate_name = tokens[1]
        for i in range(columns):
            results[gate_name][i].append(float(tokens[i + 2]))

    # calculate the median value for each column
    output = {}
    for name, data in results.items():
        medians = [(statistics.median(col) if len(col) > 0 else 0.0) for col in data]
        means = [(statistics.mean(col) if len(col) > 0 else 0.0) for col in data]
        stds = [(statistics.stdev(col) if len(col) > 0 else 0.0) for col in data]
        output[name] = list(zip(medians, means, stds))
    return output


def rprint(text: str):
    """Print text and then print `\r`"""
    print(text, end="\r", file=sys.stdout, flush=True)
