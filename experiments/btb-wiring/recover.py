"""Recover cross-function BTB weird-register edges from a TAE-style ELF.

The substrate is the one in third_party/tae/src/WeirdStates/IndirectJmp.cpp:
each slot is `jmp *%rbx` on a 32-byte stride, and the decode table is
`movw $imm, %ax; ret` on a 5-byte stride. A write loads rbx with a table
pointer and calls the slot. A read loads rbx with anything else and calls
the same slot. Edges join a write to a later read of the same slot when
the call graph can carry that value (caller into callee, or callee back
to a read after the call). Opaque indexes stay partial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from capstone import CS_ARCH_X86, CS_MODE_64, CS_OPT_SYNTAX_INTEL, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG, X86_REG_INVALID, X86_REG_RIP
from elftools.elf.elffile import ELFFile

ALIGN = 32
TBL_STRIDE = 5
JMP_RBX = b"\xff\xe3"


@dataclass
class Function:
    name: str
    start: int
    end: int


@dataclass
class Site:
    pc: int
    func: str
    kind: str
    slot: int | None = None
    partial_base: int | None = None
    dynamic: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class Event:
    kind: str  # write, read, call
    pc: int
    func: str
    slot: int | None = None
    target: str | None = None


@dataclass
class Edge:
    slot: int
    write_pc: int
    read_pc: int
    write_func: str
    read_func: str

    @property
    def cross(self) -> bool:
        return self.write_func != self.read_func

    def pair(self) -> tuple[str, str, int]:
        return (self.write_func, self.read_func, self.slot)

    def pcs(self) -> tuple[int, int, int]:
        return (self.write_pc, self.read_pc, self.slot)


@dataclass
class Program:
    path: Path
    sections: list[tuple[int, bytes]]
    insns: dict[int, object]
    functions: list[Function]
    func_starts: dict[int, str]
    symbols: dict[str, int]
    entry: int
    loads: list[tuple[int, bytes]]
    jmpreg_base: int
    nslots: int
    table_base: int
    nentries: int
    source: str

    def func_at(self, addr: int) -> str | None:
        for fn in self.functions:
            if fn.start <= addr < fn.end:
                return fn.name
        return None

    def in_table(self, addr: int) -> bool:
        return self.table_base <= addr < self.table_base + self.nentries * TBL_STRIDE

    def slot_addr(self, slot: int) -> int:
        return self.jmpreg_base + slot * ALIGN


@dataclass
class Recovery:
    program: Program
    sites: list[Site]
    edges: list[Edge]
    unknown_mnemonics: list[str]

    def cross_pairs(self) -> set[tuple[str, str, int]]:
        return {e.pair() for e in self.edges if e.cross}

    def cross_pcs(self) -> set[tuple[int, int, int]]:
        return {e.pcs() for e in self.edges if e.cross}


def _md() -> Cs:
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    md.syntax = CS_OPT_SYNTAX_INTEL
    return md


def canon(name: str) -> str:
    n = name.lower()
    legacy = {
        "rax": "rax", "eax": "rax", "ax": "rax", "ah": "rax", "al": "rax",
        "rbx": "rbx", "ebx": "rbx", "bx": "rbx", "bh": "rbx", "bl": "rbx",
        "rcx": "rcx", "ecx": "rcx", "cx": "rcx", "ch": "rcx", "cl": "rcx",
        "rdx": "rdx", "edx": "rdx", "dx": "rdx", "dh": "rdx", "dl": "rdx",
        "rsi": "rsi", "esi": "rsi", "si": "rsi", "sil": "rsi",
        "rdi": "rdi", "edi": "rdi", "di": "rdi", "dil": "rdi",
        "rbp": "rbp", "ebp": "rbp", "bp": "rbp", "bpl": "rbp",
        "rsp": "rsp", "esp": "rsp", "sp": "rsp", "spl": "rsp",
        "rip": "rip",
    }
    if n in legacy:
        return legacy[n]
    if len(n) >= 2 and n[0] == "r" and n[1:].isdigit():
        return n
    if len(n) >= 3 and n[0] == "r" and n[-1] in "dwb" and n[1:-1].isdigit():
        return n[:-1]
    return n


def width_of(name: str) -> int:
    n = name.lower()
    if n in {"rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp", "rip"}:
        return 64
    if n.startswith("r") and n[1:].isdigit():
        return 64
    if n in {"eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp"} or (
        n.startswith("r") and n.endswith("d") and n[1:-1].isdigit()
    ):
        return 32
    if n in {"ax", "bx", "cx", "dx", "si", "di", "bp", "sp"} or (
        n.startswith("r") and n.endswith("w") and n[1:-1].isdigit()
    ):
        return 16
    return 8


def _reg(ins, op) -> str:
    return ins.reg_name(op.reg)


def _contains(expr, tag: str) -> bool:
    if expr is None:
        return tag == "unk"
    if not isinstance(expr, tuple):
        return False
    if expr[0] == tag:
        return True
    return any(_contains(part, tag) for part in expr[1:] if isinstance(part, tuple))


def _read(defs: dict, name: str):
    expr = defs.get(canon(name), ("unk",))
    w = width_of(name)
    if w == 16:
        return ("lo16", expr)
    if w == 8:
        return ("lo8", expr)
    return expr


def _write(defs: dict, name: str, expr) -> None:
    defs[canon(name)] = expr if width_of(name) >= 32 else ("lo16", expr)


def is_table(expr, prog: Program) -> bool:
    found = False

    def walk(node) -> None:
        nonlocal found
        if found or not isinstance(node, tuple):
            return
        if node[0] in ("lo16", "lo8", "unk", "arg", "call"):
            return
        if node[0] in ("imm", "rip"):
            if prog.in_table(node[1]):
                found = True
            return
        for part in node[1:]:
            if isinstance(part, tuple):
                walk(part)

    walk(expr)
    return found


def _split(expr) -> tuple[int, list[str]]:
    """Split an address offset into a concrete byte constant and dyn names."""
    if not isinstance(expr, tuple):
        return 0, ["unk"]
    tag = expr[0]
    if tag == "imm":
        return int(expr[1]), []
    if tag == "arg":
        return 0, [f"arg{expr[1]}"]
    if tag == "call":
        return 0, [str(expr[1])]
    if tag == "unk":
        return 0, ["unk"]
    if tag == "add":
        c1, d1 = _split(expr[1])
        c2, d2 = _split(expr[2])
        return c1 + c2, d1 + d2
    if tag == "mul" and isinstance(expr[2], int):
        c, d = _split(expr[1])
        return c * expr[2], d
    if tag == "shl" and isinstance(expr[2], int):
        c, d = _split(expr[1])
        return c << expr[2], d
    if tag == "and" and isinstance(expr[2], tuple) and expr[2][0] == "imm":
        c, d = _split(expr[1])
        return c & int(expr[2][1]), d
    if tag in ("lo16", "lo8"):
        c, d = _split(expr[1])
        mask = 0xFFFF if tag == "lo16" else 0xFF
        return c & mask, d
    return 0, [tag]


def _slot_from_addr(prog: Program, addr: int) -> int | None:
    if addr < prog.jmpreg_base:
        return None
    delta = addr - prog.jmpreg_base
    if delta % ALIGN != 0:
        return None
    slot = delta // ALIGN
    if 0 <= slot < prog.nslots:
        return slot
    return None


def fold_slot(prog: Program, expr) -> dict | None:
    if not isinstance(expr, tuple):
        return None
    if expr[0] in ("imm", "rip"):
        slot = _slot_from_addr(prog, int(expr[1]))
        if slot is None:
            return None
        return {"kind": "concrete", "slot": slot, "dyn": []}
    if expr[0] != "add":
        return None
    base = off = None
    for addr_side, off_side in ((expr[1], expr[2]), (expr[2], expr[1])):
        if isinstance(addr_side, tuple) and addr_side[0] in ("imm", "rip"):
            base, off = int(addr_side[1]), off_side
            break
    if base is None:
        return None
    const, dyn = _split(off)
    addr = base + const
    if (addr - prog.jmpreg_base) % ALIGN != 0:
        return None
    slot = (addr - prog.jmpreg_base) // ALIGN
    if not (0 <= slot < prog.nslots):
        return None
    if dyn:
        return {"kind": "partial", "slot": slot, "dyn": dyn}
    return {"kind": "concrete", "slot": slot, "dyn": []}


def _longest_run(addrs: list[int], stride: int) -> list[int]:
    addrs = sorted(set(addrs))
    best: list[int] = []
    i = 0
    while i < len(addrs):
        run = [addrs[i]]
        j = i
        while j + 1 < len(addrs) and addrs[j + 1] == run[-1] + stride:
            j += 1
            run.append(addrs[j])
        if len(run) > len(best):
            best = run
        i = j + 1
    return best


def _find_substrate(sections: list[tuple[int, bytes]]) -> tuple[int, int, int, int]:
    jmp_addrs = []
    entries = []
    for base, blob in sections:
        for off in range(0, max(0, len(blob) - 1)):
            if blob[off : off + 2] == JMP_RBX and (base + off) % ALIGN == 0:
                jmp_addrs.append(base + off)
        off = 0
        while off + TBL_STRIDE <= len(blob):
            if blob[off] == 0x66 and blob[off + 1] == 0xB8 and blob[off + 4] == 0xC3:
                imm = int.from_bytes(blob[off + 2 : off + 4], "little")
                entries.append((base + off, imm))
                off += TBL_STRIDE
            else:
                off += 1
    run = _longest_run(jmp_addrs, ALIGN)
    if len(run) < 4:
        raise RuntimeError(f"BTB slot run not found (candidates={len(jmp_addrs)})")
    seq = _longest_entry_run(entries)
    if len(seq) < 8:
        raise RuntimeError(f"decode table not found (candidates={len(entries)})")
    return run[0], len(run), seq[0][0], len(seq)


def _longest_entry_run(entries: list[tuple[int, int]]) -> list[tuple[int, int]]:
    entries = sorted(set(entries))
    best: list[tuple[int, int]] = []
    i = 0
    while i < len(entries):
        run = [entries[i]]
        j = i
        while (
            j + 1 < len(entries)
            and entries[j + 1][0] == run[-1][0] + TBL_STRIDE
            and entries[j + 1][1] == run[-1][1] + 1
        ):
            j += 1
            run.append(entries[j])
        if len(run) > len(best):
            best = run
        i = j + 1
    return best


def _load_sections(path: Path) -> tuple[list[tuple[int, bytes]], int, dict[str, tuple[int, int, str]], list]:
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        entry = int(elf.header.e_entry)
        sections = []
        image = []
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD":
                continue
            image.append((int(seg["p_vaddr"]), bytes(seg.data())))
        for sec in elf.iter_sections():
            if sec["sh_flags"] & 0x4 and sec.data():
                sections.append((int(sec["sh_addr"]), bytes(sec.data())))
        symbols: dict[str, tuple[int, int, str]] = {}
        symtab = elf.get_section_by_name(".symtab")
        if symtab is not None:
            for sym in symtab.iter_symbols():
                name = sym.name
                if not name:
                    continue
                symbols[name] = (
                    int(sym["st_value"]),
                    int(sym["st_size"]),
                    sym["st_info"]["type"],
                )
    return sections, entry, symbols, image


def _disasm_range(md: Cs, sections: list[tuple[int, bytes]], start: int, size: int) -> list:
    blob = None
    base = None
    for sec_base, data in sections:
        if sec_base <= start < sec_base + len(data):
            blob, base = data, sec_base
            break
    if blob is None:
        return []
    off = start - base
    end = min(len(blob), off + size)
    out = []
    for ins in md.disasm(blob[off:end], start):
        if ins.address >= start + size:
            break
        out.append(ins)
    return out


def _functions_from_symbols(symbols, substrate_lo, substrate_hi) -> list[Function]:
    raw = []
    for name, (addr, size, typ) in symbols.items():
        if typ != "STT_FUNC" or size <= 0 or addr == 0:
            continue
        if substrate_lo <= addr < substrate_hi:
            continue
        end = addr + size
        if addr < substrate_lo:
            end = min(end, substrate_lo)
        if end <= addr:
            continue
        raw.append((addr, end, name))
    raw.sort()
    by_addr: dict[int, tuple[int, int, str]] = {}
    for addr, end, name in raw:
        prev = by_addr.get(addr)
        if prev is None or (prev[2].startswith("_Z") and not name.startswith("_Z")):
            by_addr[addr] = (addr, end, name)
    return [Function(name, addr, end) for addr, end, name in sorted(by_addr.values())]


def _functions_from_calls(insns_by_addr, entry, substrate_lo, substrate_hi, image_end) -> list[Function]:
    entries = set()
    if entry and not (substrate_lo <= entry < substrate_hi):
        entries.add(entry)
    for addr, ins in insns_by_addr.items():
        if ins.mnemonic not in ("call", "jmp") or not ins.operands:
            continue
        op = ins.operands[0]
        if op.type != X86_OP_IMM:
            continue
        target = int(op.imm)
        if substrate_lo <= target < substrate_hi:
            continue
        entries.add(target)
    entries = {e for e in entries if not (substrate_lo <= e < substrate_hi)}
    bounds = sorted(entries | {substrate_lo, image_end})
    funcs = []
    for ent in sorted(entries):
        end = min(b for b in bounds if b > ent)
        funcs.append(Function(f"sub_{ent:x}", ent, end))
    return funcs


def load_program(path: Path) -> Program:
    path = Path(path)
    sections, entry, symbols, image = _load_sections(path)
    jbase, nslots, tbase, nentries = _find_substrate(sections)
    substrate_lo = min(jbase, tbase)
    substrate_hi = max(jbase + nslots * ALIGN, tbase + nentries * TBL_STRIDE)
    md = _md()
    # Clip symbol extents so a padded .text does not swallow the substrate.
    funcs = _functions_from_symbols(symbols, jbase, jbase + nslots * ALIGN)
    # The decode table is a STT_FUNC too; drop it and anything inside it.
    table_hi = tbase + nentries * TBL_STRIDE
    funcs = [fn for fn in funcs if not (tbase <= fn.start < table_hi) and not (jbase <= fn.start < jbase + nslots * ALIGN)]
    source = "symbols"
    insns: dict[int, object] = {}
    if len(funcs) >= 2:
        for fn in funcs:
            for ins in _disasm_range(md, sections, fn.start, fn.end - fn.start):
                insns[ins.address] = ins
    else:
        source = "call-targets"
        # Bootstrap: linear-sweep each executable section. These fixtures are
        # small and instruction-aligned; the substrate itself is re-disassembled
        # explicitly below so a slipped byte cannot hide a slot.
        for base, blob in sections:
            off = 0
            while off < len(blob):
                chunk = list(md.disasm(blob[off:], base + off))
                if not chunk:
                    off += 1
                    continue
                for ins in chunk:
                    insns[ins.address] = ins
                nxt = chunk[-1].address + chunk[-1].size - base
                off = nxt if nxt > off else off + 1
        image_end = max(base + len(blob) for base, blob in sections)
        funcs = _functions_from_calls(insns, entry, substrate_lo, substrate_hi, image_end)
        # Re-disassemble each recovered extent from its entry so the walk
        # starts on a real instruction.
        insns = {a: i for a, i in insns.items() if substrate_lo <= a < substrate_hi}
        for fn in funcs:
            for ins in _disasm_range(md, sections, fn.start, fn.end - fn.start):
                insns[ins.address] = ins
    for slot in range(nslots):
        for ins in _disasm_range(md, sections, jbase + slot * ALIGN, ALIGN):
            insns[ins.address] = ins
            break
    for i in range(nentries):
        for ins in _disasm_range(md, sections, tbase + i * TBL_STRIDE, TBL_STRIDE):
            insns[ins.address] = ins
    sym_addrs = {name: addr for name, (addr, _size, _typ) in symbols.items()}
    return Program(
        path=path,
        sections=sections,
        insns=insns,
        functions=funcs,
        func_starts={fn.start: fn.name for fn in funcs},
        symbols=sym_addrs,
        entry=entry,
        loads=image,
        jmpreg_base=jbase,
        nslots=nslots,
        table_base=tbase,
        nentries=nentries,
        source=source,
    )


def _lea_expr(ins, defs: dict):
    dst, src = ins.operands
    mem = src.mem
    if mem.base == X86_REG_RIP and not mem.index:
        return ins.address + ins.size + int(mem.disp)
    parts = []
    if mem.base and mem.base != X86_REG_INVALID and mem.base != X86_REG_RIP:
        parts.append(_read(defs, ins.reg_name(mem.base)))
    if mem.index and mem.index != X86_REG_INVALID:
        idx = _read(defs, ins.reg_name(mem.index))
        scale = int(mem.scale or 1)
        if scale not in (0, 1):
            idx = ("mul", idx, scale)
        parts.append(idx)
    if mem.disp:
        parts.append(("imm", int(mem.disp)))
    if not parts:
        return ("imm", int(mem.disp))
    # rdi+rdi*4 is base*5 when base and index are the same register.
    if (
        mem.base
        and mem.index
        and mem.base == mem.index
        and int(mem.scale or 1) == 4
    ):
        base = _read(defs, ins.reg_name(mem.base))
        expr = ("mul", base, 5)
        if mem.disp:
            expr = ("add", expr, ("imm", int(mem.disp)))
        return expr
    expr = parts[0]
    for part in parts[1:]:
        expr = ("add", expr, part)
    return expr


def _apply(ins, defs: dict, expr_stack: list) -> str | None:
    m = ins.mnemonic
    if m in {"nop", "endbr64", "int3", "hlt", "ud2"}:
        return None
    if m == "xchg" and len(ins.operands) == 2:
        a, b = ins.operands
        if a.type == X86_OP_REG and b.type == X86_OP_REG and canon(_reg(ins, a)) == canon(_reg(ins, b)):
            return None
    if m == "push" and ins.operands and ins.operands[0].type == X86_OP_REG:
        expr_stack.append(_read(defs, _reg(ins, ins.operands[0])))
        return None
    if m == "pop" and ins.operands and ins.operands[0].type == X86_OP_REG:
        expr = expr_stack.pop() if expr_stack else ("unk",)
        _write(defs, _reg(ins, ins.operands[0]), expr)
        return None
    if m == "lea" and len(ins.operands) == 2 and ins.operands[1].type == X86_OP_MEM:
        expr = _lea_expr(ins, defs)
        if isinstance(expr, int):
            expr = ("rip", expr)
        _write(defs, _reg(ins, ins.operands[0]), expr)
        return None
    if m == "movzx" and len(ins.operands) == 2 and ins.operands[1].type == X86_OP_REG:
        _write(defs, _reg(ins, ins.operands[0]), _read(defs, _reg(ins, ins.operands[1])))
        return None
    if m == "movsxd" and len(ins.operands) == 2 and ins.operands[1].type == X86_OP_REG:
        _write(defs, _reg(ins, ins.operands[0]), _read(defs, _reg(ins, ins.operands[1])))
        return None
    if m == "mov" and len(ins.operands) == 2:
        dst, src = ins.operands
        if dst.type == X86_OP_REG and src.type == X86_OP_REG:
            _write(defs, _reg(ins, dst), _read(defs, _reg(ins, src)))
            return None
        if dst.type == X86_OP_REG and src.type == X86_OP_IMM:
            _write(defs, _reg(ins, dst), ("imm", int(src.imm)))
            return None
        if dst.type == X86_OP_MEM or src.type == X86_OP_MEM:
            if dst.type == X86_OP_REG:
                _write(defs, _reg(ins, dst), ("unk",))
            return None
    if m == "xor" and len(ins.operands) == 2:
        a, b = ins.operands
        if a.type == X86_OP_REG and b.type == X86_OP_REG and canon(_reg(ins, a)) == canon(_reg(ins, b)):
            _write(defs, _reg(ins, a), ("imm", 0))
            return None
    if m in {"add", "shl", "and", "imul", "or", "sub"}:
        return _apply_alu(ins, defs)
    if m in {"call", "jmp", "ret"}:
        return None
    return m


def _apply_alu(ins, defs: dict) -> str | None:
    m = ins.mnemonic
    ops = ins.operands
    if m == "imul" and len(ops) == 3 and ops[2].type == X86_OP_IMM:
        src = _read(defs, _reg(ins, ops[1])) if ops[1].type == X86_OP_REG else ("unk",)
        _write(defs, _reg(ins, ops[0]), ("mul", src, int(ops[2].imm)))
        return None
    if m == "shl" and len(ops) == 2 and ops[0].type == X86_OP_REG and ops[1].type == X86_OP_IMM:
        _write(defs, _reg(ins, ops[0]), ("shl", _read(defs, _reg(ins, ops[0])), int(ops[1].imm)))
        return None
    if m == "and" and len(ops) == 2 and ops[0].type == X86_OP_REG and ops[1].type == X86_OP_IMM:
        _write(defs, _reg(ins, ops[0]), ("and", _read(defs, _reg(ins, ops[0])), ("imm", int(ops[1].imm))))
        return None
    if m in {"add", "sub", "or"} and len(ops) == 2 and ops[0].type == X86_OP_REG:
        left = _read(defs, _reg(ins, ops[0]))
        if ops[1].type == X86_OP_REG:
            right = _read(defs, _reg(ins, ops[1]))
        elif ops[1].type == X86_OP_IMM:
            right = ("imm", int(ops[1].imm))
        else:
            right = ("unk",)
        _write(defs, _reg(ins, ops[0]), (m if m != "or" else "or", left, right))
        return None
    return m


def _target_expr(ins, defs: dict):
    op = ins.operands[0]
    if op.type == X86_OP_IMM:
        return ("imm", int(op.imm)), int(op.imm)
    if op.type == X86_OP_REG:
        expr = defs.get(canon(_reg(ins, op)), ("unk",))
        addr = int(expr[1]) if isinstance(expr, tuple) and expr and expr[0] == "imm" else None
        return expr, addr
    return ("unk",), None


def _walk_function(prog: Program, fn: Function, unknown: list[str]) -> tuple[list[Site], list[Event]]:
    defs = {f"r{i}": ("unk",) for i in range(8, 16)}
    for reg in ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp"):
        defs[reg] = ("unk",)
    for i, reg in enumerate(("rdi", "rsi", "rdx", "rcx", "r8", "r9")):
        defs[reg] = ("arg", i)
    expr_stack: list = []
    sites: list[Site] = []
    events: list[Event] = []
    body = [ins for addr, ins in sorted(prog.insns.items()) if fn.start <= addr < fn.end]
    for ins in body:
        if ins.mnemonic in {"call", "jmp"} and ins.operands:
            expr, addr = _target_expr(ins, defs)
            folded = fold_slot(prog, expr)
            in_slots = addr is not None and _slot_from_addr(prog, addr) is not None
            if folded is not None or in_slots:
                if folded is None and addr is not None:
                    folded = {"kind": "concrete", "slot": _slot_from_addr(prog, addr), "dyn": []}
                rbx = defs.get("rbx", ("unk",))
                table = is_table(rbx, prog)
                kind = "unknown"
                slot = folded["slot"] if folded else None
                partial_base = None
                dyn = list(folded["dyn"]) if folded else []
                if folded and folded["kind"] == "concrete" and table:
                    kind = "write"
                elif folded and folded["kind"] == "concrete" and not _contains(rbx, "unk"):
                    kind = "read"
                elif folded and folded["kind"] == "partial" and table:
                    kind = "partial-write"
                    partial_base = slot
                elif folded and folded["kind"] == "partial" and not _contains(rbx, "unk"):
                    kind = "partial-read"
                    partial_base = slot
                site = Site(ins.address, fn.name, kind, slot if kind in {"write", "read"} else None, partial_base, dyn)
                if kind in {"write", "read"}:
                    events.append(Event(kind, ins.address, fn.name, slot=slot))
                sites.append(site)
                defs["rax"] = ("unk",)
                continue
            if ins.mnemonic in {"call", "jmp"} and addr in prog.func_starts and addr != fn.start:
                events.append(Event("call", ins.address, fn.name, target=prog.func_starts[addr]))
                defs["rax"] = ("call", prog.func_starts[addr])
                continue
        unknown_m = _apply(ins, defs, expr_stack)
        if unknown_m:
            unknown.append(f"{ins.address:#x} {unknown_m} {ins.op_str}")
    return sites, events


def _reads_before_write(events: dict[str, list[Event]], fn: str, slot: int, seen: set[str]) -> list[Event]:
    if fn in seen or fn not in events:
        return []
    seen = seen | {fn}
    out = []
    for ev in events[fn]:
        if ev.kind == "write" and ev.slot == slot:
            break
        if ev.kind == "read" and ev.slot == slot:
            out.append(ev)
        elif ev.kind == "call" and ev.target:
            out.extend(_reads_before_write(events, ev.target, slot, seen))
            if _writes_slot(events, ev.target, slot, seen):
                break
    return out


def _last_writes(events: dict[str, list[Event]], fn: str, seen: set[str]) -> dict[int, Event]:
    if fn in seen or fn not in events:
        return {}
    seen = seen | {fn}
    visible: dict[int, Event] = {}
    for ev in events[fn]:
        if ev.kind == "write" and ev.slot is not None:
            visible[ev.slot] = ev
        elif ev.kind == "call" and ev.target:
            for slot, write in _last_writes(events, ev.target, seen).items():
                visible[slot] = write
    return visible


def _writes_slot(events, fn: str, slot: int, seen: set[str]) -> bool:
    return slot in _last_writes(events, fn, set(seen))


def _match(events: dict[str, list[Event]]) -> list[Edge]:
    edges: list[Edge] = []
    seen_pc: set[tuple[int, int, int]] = set()

    def emit(write: Event, read: Event) -> None:
        if write.slot != read.slot or write.slot is None:
            return
        key = (write.pc, read.pc, write.slot)
        if key in seen_pc:
            return
        seen_pc.add(key)
        edges.append(Edge(write.slot, write.pc, read.pc, write.func, read.func))

    for fn, evs in events.items():
        visible: dict[int, Event] = {}
        for ev in evs:
            if ev.kind == "write" and ev.slot is not None:
                visible[ev.slot] = ev
            elif ev.kind == "read" and ev.slot is not None and ev.slot in visible:
                emit(visible[ev.slot], ev)
            elif ev.kind == "call" and ev.target:
                for slot, write in list(visible.items()):
                    for read in _reads_before_write(events, ev.target, slot, {fn}):
                        emit(write, read)
                for slot, write in _last_writes(events, ev.target, {fn}).items():
                    visible[slot] = write
    return edges


def recover(path: Path) -> Recovery:
    prog = load_program(path)
    unknown: list[str] = []
    sites: list[Site] = []
    events: dict[str, list[Event]] = {}
    for fn in prog.functions:
        fn_sites, fn_events = _walk_function(prog, fn, unknown)
        sites.extend(fn_sites)
        events[fn.name] = fn_events
    edges = _match(events)
    return Recovery(prog, sites, edges, unknown)


def recovery_to_json(rec: Recovery) -> dict:
    return {
        "elf": str(rec.program.path),
        "functions_from": rec.program.source,
        "jmpreg_base": hex(rec.program.jmpreg_base),
        "nslots": rec.program.nslots,
        "table_base": hex(rec.program.table_base),
        "nentries": rec.program.nentries,
        "functions": [
            {"name": fn.name, "start": hex(fn.start), "end": hex(fn.end)}
            for fn in rec.program.functions
        ],
        "sites": [
            {
                "pc": hex(s.pc),
                "func": s.func,
                "kind": s.kind,
                "slot": s.slot,
                "partial_base": s.partial_base,
                "dynamic": s.dynamic,
            }
            for s in rec.sites
        ],
        "edges": [
            {
                "slot": e.slot,
                "write_pc": hex(e.write_pc),
                "read_pc": hex(e.read_pc),
                "write_func": e.write_func,
                "read_func": e.read_func,
                "cross_function": e.cross,
                "via": f"btb[{e.slot}]",
            }
            for e in rec.edges
        ],
        "cross_pairs": [
            {"write_func": a, "read_func": b, "slot": s}
            for a, b, s in sorted(rec.cross_pairs())
        ],
        "unknown_mnemonics": rec.unknown_mnemonics[:40],
    }
