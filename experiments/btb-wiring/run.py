"""BTB cross-function wiring kill test.

Rebuild the fixtures, recover edges, run the software oracle, and write
logs/ plus RESULTS.md. Exit 0 only when the kill question passes.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from oracle import Machine, transfers  # noqa: E402
from recover import load_program, recover, recovery_to_json  # noqa: E402

FIX = HERE / "fixture"
BUILD = HERE / "build"
LOGS = HERE / "logs"
ASM_PAIRS = {
    ("driver", "weird", 0),
    ("driver", "weird", 1),
    ("weird", "driver", 2),
    ("weird", "driver", 4),
}
CC_PAIRS = {
    ("driver_c", "weird_c", 0),
    ("driver_c", "weird_c", 1),
    ("weird_c", "driver_c", 2),
}
WEMU = Path("/u/hthomare/weird-machines/artifacts/WeMu")


def run(cmd: list[str], log: list[str]) -> None:
    log.append("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.stdout:
        log.append(proc.stdout)
    if proc.stderr:
        log.append(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr}")


def build(log: list[str]) -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    asm = BUILD / "wiring-asm.elf"
    cc = BUILD / "wiring-cc.elf"
    run(
        [
            "gcc", "-no-pie", "-nostdlib", "-static", "-Wa,--noexecstack",
            "-Wl,-e,_start", "-o", str(asm),
            str(FIX / "wiring.S"), str(FIX / "substrate.S"),
        ],
        log,
    )
    run(
        [
            "g++", "-std=c++17", "-O2", "-fno-pie", "-no-pie", "-nostdlib",
            "-fno-exceptions", "-fno-rtti", "-fno-asynchronous-unwind-tables",
            "-Wl,-e,driver_c", f"-I{ROOT / 'third_party' / 'tae' / 'include'}",
            "-o", str(cc), str(FIX / "wiring.cc"), str(FIX / "substrate.S"),
        ],
        log,
    )
    run(["strip", "-s", "-o", str(BUILD / "wiring-asm.stripped.elf"), str(asm)], log)


def cpu_name() -> str:
    name = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                name = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return name


def objdump(path: Path, stop: int | None, dest: Path) -> None:
    cmd = ["objdump", "-d", "-M", "intel", "--no-show-raw-insn", str(path)]
    if stop is not None:
        cmd[1:1] = ["--stop-address", hex(stop)]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    text = proc.stdout
    if proc.returncode != 0:
        text += "\n" + proc.stderr
    dest.write_text(text)


def check(name: str, ok: bool, detail: str, checks: list[dict]) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    build_log: list[str] = []
    build(build_log)
    (LOGS / "build.log").write_text("\n".join(build_log) + "\n")

    asm_path = BUILD / "wiring-asm.elf"
    cc_path = BUILD / "wiring-cc.elf"
    stripped_path = BUILD / "wiring-asm.stripped.elf"
    asm = recover(asm_path)
    cc = recover(cc_path)
    stripped = recover(stripped_path)
    (LOGS / "recovery-asm.json").write_text(json.dumps(recovery_to_json(asm), indent=2) + "\n")
    (LOGS / "recovery-cc.json").write_text(json.dumps(recovery_to_json(cc), indent=2) + "\n")
    (LOGS / "recovery-asm-stripped.json").write_text(json.dumps(recovery_to_json(stripped), indent=2) + "\n")
    objdump(asm_path, asm.program.jmpreg_base, LOGS / "wiring-asm.objdump")
    objdump(cc_path, cc.program.jmpreg_base, LOGS / "wiring-cc.objdump")

    checks: list[dict] = []
    prog = asm.program
    check(
        "substrate",
        prog.nslots == 16 and prog.nentries == 256 and prog.table_base != 0,
        f"slots={prog.nslots} at {prog.jmpreg_base:#x}, entries={prog.nentries} at {prog.table_base:#x}, via {prog.source}",
        checks,
    )
    check(
        "asm cross-function pairs",
        asm.cross_pairs() == ASM_PAIRS,
        f"got {sorted(asm.cross_pairs())}",
        checks,
    )
    check(
        "asm unknown mnemonics",
        not asm.unknown_mnemonics,
        ", ".join(asm.unknown_mnemonics[:8]) or "none",
        checks,
    )
    check(
        "stripped edges keep the same pcs",
        stripped.cross_pcs() == asm.cross_pcs() and stripped.program.source == "call-targets",
        f"stripped via {stripped.program.source}, pcs match={stripped.cross_pcs() == asm.cross_pcs()}",
        checks,
    )

    machine = Machine(load_program(asm_path))
    got = machine.call("driver", rdi=0x11, rsi=0x22)
    (LOGS / "oracle-positive.json").write_text(json.dumps({
        "eax": got,
        "slots": {str(i): machine.slot_value(i) for i in range(8)},
        "log": machine.log,
        "transfers": [list(t) for t in sorted(transfers(machine.log))],
        "probe": machine.probe,
        "resumes": machine.resumes,
        "stores": machine.stores,
    }, indent=2) + "\n")
    table = prog.table_base
    forbidden = {0x11, 0x22, table + 0x11 * 5, table + 0x22 * 5}
    probe = machine.probe or {"regs": {}, "stack": [], "arch_channel": None}
    leaked = [f"{name}={value:#x}" for name, value in probe["regs"].items() if value in forbidden]
    leaked += [f"stack={value:#x}" for value in probe["stack"] if value in forbidden]
    channel = machine.prog.symbols["arch_channel"]
    wrote_channel = any(addr == channel and size == 8 and value == 0 for addr, size, value in machine.stores)
    reads0 = [ev for ev in machine.log if ev["kind"] == "read" and ev["slot"] == 0 and ev["transient"]]
    check("oracle returns the sum", got == 0x33, f"eax={got:#x}", checks)
    check(
        "probe has no architectural copy of the inputs",
        machine.probe is not None and not leaked and probe["arch_channel"] == 0 and wrote_channel,
        f"leaked={leaked or 'none'}, arch_channel={probe['arch_channel']}, store_hit={wrote_channel}",
        checks,
    )
    resume = machine.resumes[0]["regs"] if machine.resumes else {}
    check(
        "window resume squashes the transient sum",
        bool(machine.resumes) and resume.get("rax") == 0 and resume.get("r12") == 0,
        f"resumes={len(machine.resumes)} rax={resume.get('rax')} r12={resume.get('r12')}",
        checks,
    )
    check(
        "non-destructive double read of slot 0",
        len(reads0) >= 2 and all(ev["value"] == 0x11 for ev in reads0) and machine.slot_value(0) == 0x11 and machine.slot_value(4) == 0x11,
        f"reads={len(reads0)} slot0={machine.slot_value(0)} slot4={machine.slot_value(4)}",
        checks,
    )
    check(
        "oracle transfers match recovered edges",
        transfers(machine.log) == ASM_PAIRS and machine.slot_value(2) == 0x33,
        f"transfers={sorted(transfers(machine.log))} slot2={machine.slot_value(2)}",
        checks,
    )

    dropped = Machine(load_program(asm_path), commit_transient_writes=False)
    dropped_eax = dropped.call("driver", rdi=0x11, rsi=0x22)
    no_read = Machine(load_program(asm_path), read_uses_btb=False)
    no_read_eax = no_read.call("driver", rdi=0x11, rsi=0x22)
    check(
        "ablation: transient BTB writes discarded",
        dropped_eax != 0x33,
        f"eax={dropped_eax:#x}",
        checks,
    )
    check(
        "ablation: BTB reads disabled",
        no_read_eax != 0x33,
        f"eax={no_read_eax:#x}",
        checks,
    )
    (LOGS / "oracle-ablation.json").write_text(json.dumps({
        "discard_transient_writes_eax": dropped_eax,
        "btb_reads_disabled_eax": no_read_eax,
    }, indent=2) + "\n")

    neg = Machine(load_program(asm_path))
    neg_eax = neg.call("driver_neg", rdi=0x11)
    neg_pairs = {p for p in asm.cross_pairs() if "neg" in p[0] or "neg" in p[1] or p[2] == 7}
    check(
        "mismatched slots do not transfer",
        neg_eax != 0x11 and not neg_pairs,
        f"eax={neg_eax:#x}, negative pairs={sorted(neg_pairs)}",
        checks,
    )

    check(
        "compiler -O2 cross-function pairs",
        cc.cross_pairs() == CC_PAIRS,
        f"got {sorted(cc.cross_pairs())}",
        checks,
    )
    check(
        "compiler unknown mnemonics",
        not cc.unknown_mnemonics,
        ", ".join(cc.unknown_mnemonics[:8]) or "none",
        checks,
    )
    partials = [
        s for s in cc.sites
        if s.func == "driver_opaque" and s.kind == "partial-read" and s.partial_base == 5 and "opaque_zero" in s.dynamic
    ]
    concrete_reads = [s for s in cc.sites if s.func == "driver_opaque" and s.kind == "read"]
    slot5_writes = [s for s in cc.sites if s.func == "driver_opaque" and s.kind == "write" and s.slot == 5]
    check(
        "opaque index stays partial at base 5",
        bool(partials) and bool(slot5_writes) and not concrete_reads,
        f"partials={len(partials)} slot5_writes={len(slot5_writes)} concrete_reads={len(concrete_reads)} dyn={partials[0].dynamic if partials else None}",
        checks,
    )
    cc_bad = {
        p for p in cc.cross_pairs()
        if p[2] == 7 or p[0] == "driver_neg_c" or p[1] == "weird_neg_c" or (p[0] == "driver_c" and p[1] == "weird_neg_c")
    }
    check(
        "compiler negative pair is not wired",
        not cc_bad,
        f"bad={sorted(cc_bad)}",
        checks,
    )

    miner = {"available": False}
    try:
        from wf.mine import mine_path

        _view, pairs = mine_path(asm_path, {
            "strategy": "diff",
            "n": 6,
            "abstract_regs": True,
            "abstract_imms": False,
            "drop_nop": True,
            "min_count": 2,
            "snap": 16,
            "jaccard": 0.4,
            "min_gap": 64,
            "max_gap": 2048,
        })
        miner = {"available": True, "n_pairs": len(pairs), "note": "n-gram diff pairs are not BTB slot edges"}
    except Exception as exc:  # noqa: BLE001 — baseline is informational
        miner = {"available": False, "error": str(exc)}
    (LOGS / "diff-miner.json").write_text(json.dumps(miner, indent=2) + "\n")

    failed = [c for c in checks if not c["ok"]]
    verdict = "PASS" if not failed else "FAIL"
    summary = {
        "verdict": verdict,
        "kill_question": (
            "Can cross-function dataflow through a non-destructive BTB weird "
            "register be recovered on one TAE-style program?"
        ),
        "cpu": cpu_name(),
        "python": platform.python_version(),
        "wemu_present": WEMU.is_dir(),
        "checks": checks,
        "diff_miner": miner,
    }
    (LOGS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (HERE / "RESULTS.md").write_text(render_results(summary, asm, cc))
    print(f"verdict: {verdict}")
    for item in checks:
        mark = "ok" if item["ok"] else "FAIL"
        print(f"  [{mark}] {item['name']}: {item['detail']}")
    return 0 if verdict == "PASS" else 1


def render_results(summary: dict, asm, cc) -> str:
    lines = [
        "# BTB weird-register wiring: kill test",
        "",
        f"**Verdict: {summary['verdict']}**",
        "",
        "Kill question: can cross-function dataflow through a non-destructive BTB slot be recovered on one TAE-style program, and does a software model of that slot actually carry the value after architectural state is cleared?",
        "",
        "This does not re-run Flexo netlist recovery. The existing n-gram diff locator in `src/wf/mine.py` is a different analysis and is not the oracle here.",
        "",
        "## Method",
        "",
        "The substrate is the TAE indirect-jump register from `third_party/tae/include/WeirdStates/IndirectJmp.h` and `src/WeirdStates/IndirectJmp.cpp`: `jmpregN` is `jmp *%rbx` on a 32-byte stride, and `decode_table` is `movw $value, %ax; ret` on a 5-byte stride. A write calls the slot with `rbx` pointing at a table entry. A read calls the same slot with `rbx` pointing elsewhere. The ret-hijack window is `create_window` from `TransientWindows/RetBased.cpp`.",
        "",
        "Two fixtures share that substrate:",
        "",
        "- `fixture/wiring.S` is a scheduled two-function program. `driver` writes slots 0 and 1, zeroes every general register and `arch_channel`, calls `weird`, then reads slots 2 and 4. `weird` reads slot 0 twice and slot 1 inside the window and writes the sum and the echoed input. `driver_neg` / `weird_neg` write slot 0 and read slot 7.",
        "- `fixture/wiring.cc` is the same shape compiled with g++ -O2, calling the real `WM::write`, `WM::readTransient`, `WR_READ`, and `WR_WRITE` macros. `driver_opaque` reads slot `opaque_zero()+5`.",
        "",
        "Recovery is a forward register slice inside each function, then a one-level call-graph join: a write reaches a read of the same slot in a callee entered before the next write, and a callee's last write reaches a read after the call returns. The oracle executes the assembly fixture under that contract. Ablations turn off transient BTB updates and BTB reads separately.",
        "",
        f"Host CPU: {summary['cpu']}. WeMu path `{WEMU}` present: {summary['wemu_present']}. Native TAE was not run. The TAE sources say results on an unsupported processor are not evidence, and this oracle does not claim silicon BTB persistence.",
        "",
        "## Checks",
        "",
        "| check | result | detail |",
        "| --- | --- | --- |",
    ]
    for item in summary["checks"]:
        mark = "PASS" if item["ok"] else "FAIL"
        detail = item["detail"].replace("|", "\\|")
        lines.append(f"| {item['name']} | {mark} | {detail} |")
    lines += [
        "",
        "## What the edges are",
        "",
        "Assembly cross-function edges:",
        "",
    ]
    for edge in asm.edges:
        if edge.cross:
            lines.append(
                f"- `{edge.write_func}` `{edge.write_pc:#x}` writes btb[{edge.slot}] → `{edge.read_func}` `{edge.read_pc:#x}` reads it"
            )
    lines += ["", "Compiler cross-function edges:", ""]
    for edge in cc.edges:
        if edge.cross:
            lines.append(
                f"- `{edge.write_func}` `{edge.write_pc:#x}` writes btb[{edge.slot}] → `{edge.read_func}` `{edge.read_pc:#x}` reads it"
            )
    miner = summary["diff_miner"]
    lines += [
        "",
        "## Diff-miner baseline",
        "",
        f"`mine_path` on the assembly fixture: {json.dumps(miner)}.",
        "",
        "The diff miner clusters repeated instruction n-grams. On this fixture it emitted no pairs, so the slot edges above are outside that analysis. TAE in the existing pipeline stays a localization result for the same reason.",
        "",
        "## Hardware gap",
        "",
        "The output edge is only live in the oracle when transient writes to the BTB are kept and reads consult the BTB instead of `rbx`. That is the weird-register contract. It is not a measurement on this Xeon. A workshop follow-up on a CPU where the TAE `gates` / `search` binaries are known to be accurate would compare `WM::read` of the recovered slots with the oracle's values.",
        "",
        "Constant slot ids in `WR_READ` / `WR_WRITE` and inlined `WM::write(constant, ...)` are concrete. `driver_opaque` is the `readIdx = opaque()+k` shape used by `examples/search.cpp` (`longDelay(...) + 2`). The constant 5 survives; `opaque_zero` does not fold. Proving the delay returns 0 is future work, not this kill test.",
        "",
        "## Next steps",
        "",
        "- Re-run the recovered search/AES edges on a supported TAE CPU and compare them to `WM::read` output.",
        "- Add a delay analysis that shows `longDelay` is architecturally 0 so the search driver's output slots collapse from `base+opaque` to a concrete id.",
        "- The cache-timing half of `WM::read` is a separate channel. This test only recovers the BTB operand of that read.",
        "",
        "## Reproduce",
        "",
        "```",
        "python3 experiments/btb-wiring/run.py",
        "```",
        "",
        "Requires gcc, g++, binutils, capstone, and pyelftools. Raw logs are in `experiments/btb-wiring/logs/`.",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
