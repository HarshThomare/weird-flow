"""Run weird machines to reporduce the results on the paper (section 5)"""

import argparse
import os
import subprocess
import time
import util

file_path = os.path.dirname(os.path.abspath(__file__))
MEASURE_ITER = 1000


def measure_acc_runtime(wm: str, log_file: str, trials: int, timeout: int):
    """Measure the accuracy and runtime of a program"""
    # create the result csv file if not exist
    if not os.path.exists(log_file):
        with open(log_file, "w", encoding="utf-8") as ofile:
            ofile.write("Timestamp,Name,Accuracy (%),Runtime (us)\n")

    # stop measuring when the timeout expires
    end = (time.time() + timeout * 60) if timeout != -1 else None

    # run the program and append results to `result_path`
    short_name = util.short_filename(wm)
    for t in range(trials):
        util.rprint(f"Running {short_name}" + f": {t + 1}/{trials}")
        try:
            left = -1 if end is None else (end - time.time())
            results = util.run_program(wm, MEASURE_ITER, left)
            with open(log_file, "a", encoding="utf-8") as ofile:
                for name, acc, runtime in results:
                    ofile.write(f"{int(time.time())},{name},{acc:.2f},{runtime:.2f}\n")
        except subprocess.TimeoutExpired:
            print(f"[!] Timeout expires while measuring {name}")
            return

    # print((f"[*] Done measuring {short_name}").ljust(80))


def report(filename: str):
    """Output the median accuracy and runtime for each program"""
    output = (
        "Program,".ljust(15)
        + "Accuracy (med/mean/std),".rjust(25)
        + "Runtime (med/mean/std)".rjust(29)
        + "\n"
    )
    results = util.median_result(filename, 2)
    for name, outcome in results.items():
        line = (
            f"{name},".ljust(15)
            + (("/".join([f"{r:.2f}%" for r in outcome[0]])) + ",").rjust(25)
            + ("/".join([f"{r:.2f} us" for r in outcome[1]])).rjust(29)
        )
        output += line + "\n"

    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run WM: measure the accuracy and runtime of weird programs."
    )
    parser.add_argument("filename")
    parser.add_argument(
        "-r",
        "--report",
        action="store_true",
        help="Report the existing results without running the weird machines again",
    )
    parser.add_argument(
        "-i",
        "--iterations",
        type=int,
        default=100,
        help="Number of iterations to measure the accuracy and runtime",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=5,
        help="Timeout in minutes for each weird program",
    )
    parser.add_argument(
        "-l",
        "--logs",
        type=str,
        default=os.path.join(file_path, "./logs"),
        help="Directory to store the log files (default to [script dir]/logs)",
    )
    args = parser.parse_args()
    logs = os.path.normpath(args.logs)

    # create the result directory if not exists
    if not os.path.exists(logs):
        os.mkdir(logs)

    # run the experiments
    if not args.report:
        wm_name = util.short_filename(args.filename)
        date_time = time.strftime("%m-%d-%H_%M")
        log_filename = os.path.join(logs, f"{wm_name}-{date_time}.csv")
        measure_acc_runtime(args.filename, log_filename, args.iterations, args.timeout)
        print(f"[*] Results are saved to {log_filename}")

    # report median accuracy and runtime
    report(args.filename if args.report else log_filename)
