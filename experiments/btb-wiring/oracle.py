"""Software oracle for one TAE-style BTB weird register.

This is not a CPU. It executes the hand-written fixture and models the
contract in third_party/tae:

- `jmp *%rbx` at jmpregN trains btb[N] when rbx points into decode_table.
- A read (rbx outside the table) reuses that target and does not replace it.
- WM::createWindow (`mov [rsp], dest; ret`) runs the bytes after the call
  only transiently. Register and stack updates from that window are
  discarded. BTB updates from the window survive unless the ablation
  `commit_transient_writes` is off.

WeMu is not in this tree, and this VM is not a published TAE platform, so
the oracle is the differential check for the kill test.
"""

from __future__ import annotations

from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG, X86_REG_INVALID, X86_REG_RIP

from recover import Program, canon, width_of

MASK64 = (1 << 64) - 1
STOP = 0x1
SENTINEL = 0xFFFF


class Mem:
    def __init__(self, loads: list[tuple[int, bytes]]):
        self.b: dict[int, int] = {}
        for base, blob in loads:
            for i, byte in enumerate(blob):
                self.b[base + i] = byte

    def read(self, addr: int, n: int) -> int:
        value = 0
        for i in range(n):
            value |= self.b.get(addr + i, 0) << (8 * i)
        return value

    def write(self, addr: int, n: int, value: int) -> None:
        for i in range(n):
            self.b[addr + i] = (value >> (8 * i)) & 0xFF


class Machine:
    def __init__(
        self,
        prog: Program,
        *,
        read_uses_btb: bool = True,
        commit_transient_writes: bool = True,
    ):
        self.prog = prog
        self.read_uses_btb = read_uses_btb
        self.commit_transient_writes = commit_transient_writes
        self.mem = Mem(prog.loads)
        self.regs = {name: 0 for name in (
            "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
            "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
        )}
        self.stack: list[int] = []
        self.btb: dict[int, int] = {}
        self.pc = 0
        self.transient = False
        self.pending = False
        self.pending_old = 0
        self.pending_new = 0
        self.log: list[dict] = []
        self.probe: dict | None = None
        self.resumes: list[dict] = []
        self.stores: list[tuple[int, int, int]] = []
        self.steps = 0

    def call(self, name: str, **regs: int) -> int:
        addr = self.prog.symbols[name]
        for reg in self.regs:
            self.regs[reg] = 0
        for reg, value in regs.items():
            self.regs[canon(reg)] = value & MASK64
        self.stack = [STOP]
        self.btb = {}
        self.log = []
        self.probe = None
        self.resumes = []
        self.stores = []
        self.pending = False
        self.transient = False
        self.pc = addr
        self.steps = 0
        while self.pc != STOP:
            self.step()
            self.steps += 1
            if self.steps > 100000:
                raise RuntimeError(f"step limit at {self.pc:#x}")
        return self.regs["rax"]

    def slot_value(self, slot: int) -> int | None:
        target = self.btb.get(slot)
        if target is None or not self.prog.in_table(target):
            return None
        return (target - self.prog.table_base) // 5

    def step(self) -> None:
        ins = self.prog.insns.get(self.pc)
        if ins is None:
            raise RuntimeError(f"no instruction at {self.pc:#x}")
        m = ins.mnemonic
        if m in {"nop", "endbr64"}:
            self.pc += ins.size
            return
        if m == "lea":
            self._lea(ins)
            return
        if m == "movzx":
            self._set(ins.operands[0], self._src(ins, ins.operands[1]) & 0xFFFF, 32)
            self.pc += ins.size
            return
        if m == "mov":
            self._mov(ins)
            return
        if m == "xor":
            self._alu(ins, lambda a, b: a ^ b)
            return
        if m == "add":
            self._alu(ins, lambda a, b: a + b)
            return
        if m == "imul":
            dst, src, imm = ins.operands
            value = (self._src(ins, src) * int(imm.imm)) & MASK64
            self._set(dst, value, width_of(ins.reg_name(dst.reg)))
            self.pc += ins.size
            return
        if m == "call":
            self._call(ins)
            return
        if m == "jmp":
            self._jmp(ins)
            return
        if m == "ret":
            self._ret()
            return
        raise RuntimeError(f"unimplemented {self.pc:#x}: {ins.mnemonic} {ins.op_str}")

    def _set(self, op, value: int, width: int | None = None) -> None:
        reg = canon(self._current_reg(op))
        if width is None:
            width = 64
        value &= MASK64
        if width >= 32:
            if width == 32:
                value &= 0xFFFFFFFF
            self.regs[reg] = value
            return
        if width == 16:
            self.regs[reg] = (self.regs[reg] & ~0xFFFF) | (value & 0xFFFF)
            return
        self.regs[reg] = (self.regs[reg] & ~0xFF) | (value & 0xFF)

    def _current_reg(self, op) -> str:
        ins = self.prog.insns[self.pc]
        return ins.reg_name(op.reg)

    def _src(self, ins, op) -> int:
        if op.type == X86_OP_IMM:
            return int(op.imm) & MASK64
        if op.type == X86_OP_REG:
            full = self.regs[canon(ins.reg_name(op.reg))]
            w = width_of(ins.reg_name(op.reg))
            if w == 32:
                return full & 0xFFFFFFFF
            if w == 16:
                return full & 0xFFFF
            if w == 8:
                return full & 0xFF
            return full & MASK64
        raise RuntimeError(f"bad source at {ins.address:#x}")

    def _lea(self, ins) -> None:
        dst, src = ins.operands
        mem = src.mem
        if mem.base == X86_REG_RIP and not mem.index:
            value = ins.address + ins.size + int(mem.disp)
        else:
            value = int(mem.disp)
            if mem.base and mem.base != X86_REG_INVALID and mem.base != X86_REG_RIP:
                value += self.regs[canon(ins.reg_name(mem.base))]
            if mem.index and mem.index != X86_REG_INVALID:
                value += self.regs[canon(ins.reg_name(mem.index))] * int(mem.scale or 1)
        self._set(dst, value, width_of(ins.reg_name(dst.reg)))
        self.pc += ins.size

    def _mov(self, ins) -> None:
        dst, src = ins.operands
        if dst.type == X86_OP_REG and src.type in (X86_OP_REG, X86_OP_IMM):
            self._set(dst, self._src(ins, src), width_of(ins.reg_name(dst.reg)))
            self.pc += ins.size
            return
        if dst.type == X86_OP_MEM and self._is_stack_top(dst):
            value = self._src(ins, src)
            self.pending_old = self.stack[-1]
            self.pending_new = value
            self.pending = True
            self.stack[-1] = value
            self.pc += ins.size
            return
        if dst.type == X86_OP_MEM and src.type in (X86_OP_REG, X86_OP_IMM):
            addr = self._mem_addr(ins, dst)
            size = dst.size or 8
            value = self._src(ins, src)
            self.mem.write(addr, size, value)
            self.stores.append((addr, size, value))
            self.pc += ins.size
            return
        if dst.type == X86_OP_REG and src.type == X86_OP_MEM:
            addr = self._mem_addr(ins, src)
            self._set(dst, self.mem.read(addr, src.size or 8), width_of(ins.reg_name(dst.reg)))
            self.pc += ins.size
            return
        raise RuntimeError(f"bad mov at {ins.address:#x}: {ins.op_str}")

    def _is_stack_top(self, op) -> bool:
        mem = op.mem
        return (
            mem.base != X86_REG_RIP
            and mem.base
            and canon(self.prog.insns[self.pc].reg_name(mem.base)) == "rsp"
            and not mem.index
            and int(mem.disp) == 0
        )

    def _mem_addr(self, ins, op) -> int:
        mem = op.mem
        if mem.base == X86_REG_RIP and not mem.index:
            return ins.address + ins.size + int(mem.disp)
        addr = int(mem.disp)
        if mem.base and mem.base != X86_REG_INVALID and mem.base != X86_REG_RIP:
            addr += self.regs[canon(ins.reg_name(mem.base))]
        if mem.index and mem.index != X86_REG_INVALID:
            addr += self.regs[canon(ins.reg_name(mem.index))] * int(mem.scale or 1)
        return addr & MASK64

    def _alu(self, ins, fn) -> None:
        dst, src = ins.operands
        if dst.type == X86_OP_REG and src.type == X86_OP_REG and canon(ins.reg_name(dst.reg)) == canon(ins.reg_name(src.reg)) and ins.mnemonic == "xor":
            self._set(dst, 0, width_of(ins.reg_name(dst.reg)))
            self.pc += ins.size
            return
        value = fn(self._src(ins, dst), self._src(ins, src))
        self._set(dst, value, width_of(ins.reg_name(dst.reg)))
        self.pc += ins.size

    def _call(self, ins) -> None:
        target = int(ins.operands[0].imm)
        ret = ins.address + ins.size
        if target == self.prog.symbols.get("oracle_probe"):
            self.probe = self._snapshot()
        self.stack.append(ret)
        self.pc = target

    def _jmp(self, ins) -> None:
        op = ins.operands[0]
        if op.type == X86_OP_REG and canon(ins.reg_name(op.reg)) == "rbx":
            self._btb_jmp(ins.address)
            return
        if op.type == X86_OP_IMM:
            self.pc = int(op.imm)
            return
        raise RuntimeError(f"bad jmp at {ins.address:#x}")

    def _caller(self) -> str | None:
        if not self.stack:
            return None
        return self.prog.func_at(self.stack[-1])

    def _encoded(self, target: int) -> int | None:
        if target < self.prog.table_base:
            return None
        delta = target - self.prog.table_base
        if delta % 5 != 0:
            return None
        return delta // 5

    def _btb_jmp(self, pc: int) -> None:
        slot = (pc - self.prog.jmpreg_base) // 32
        target = self.regs["rbx"]
        trained = self.btb.get(slot)
        encoded = self._encoded(target)
        in_range = encoded is not None and encoded < self.prog.nentries
        # dummy_delay sits just past the table and can be 5-aligned. A real
        # entry is inside the table. An out-of-range encode is not an
        # instruction; jumping there is how the read ablation used to fault.
        if encoded is not None and (in_range or target not in self.prog.insns):
            commit = in_range and ((not self.transient) or self.commit_transient_writes)
            if commit:
                self.btb[slot] = target
            self.log.append({
                "kind": "write",
                "slot": slot,
                "value": encoded & 0xFFFF,
                "func": self._caller(),
                "transient": self.transient,
                "committed": commit,
                "pc": pc,
            })
            if in_range:
                self.pc = target
                return
            self.regs["rax"] = encoded & 0xFFFF
            self.pc = self.stack.pop()
            return
        use = self.read_uses_btb and trained is not None and self.prog.in_table(trained)
        if use:
            value = (trained - self.prog.table_base) // 5
            self.log.append({
                "kind": "read",
                "slot": slot,
                "value": value,
                "func": self._caller(),
                "transient": self.transient,
                "committed": True,
                "pc": pc,
            })
            self.pc = trained
            return
        self.log.append({
            "kind": "read",
            "slot": slot,
            "value": None,
            "func": self._caller(),
            "transient": self.transient,
            "committed": False,
            "pc": pc,
        })
        if self.read_uses_btb:
            self.regs["rax"] = SENTINEL
            self.pc = self.stack.pop()
            return
        self.pc = target

    def _ret(self) -> None:
        dest = self.stack.pop()
        if self.pending and not self.transient:
            old, new = self.pending_old, self.pending_new
            self.pending = False
            if dest == new and old != new and old in self.prog.insns and new in self.prog.insns:
                self._run_transient(old, new)
                self.pc = new
                return
        self.pc = dest

    def _run_transient(self, start: int, stop: int) -> None:
        saved_regs = dict(self.regs)
        saved_stack = list(self.stack)
        self.transient = True
        self.pc = start
        guard = 0
        while self.pc != stop:
            self.step()
            guard += 1
            self.steps += 1
            if guard > 10000:
                raise RuntimeError(f"transient window did not reach {stop:#x} from {start:#x}, pc={self.pc:#x}")
        self.regs = saved_regs
        self.stack = saved_stack
        self.transient = False
        self.pending = False
        self.resumes.append({"pc": stop, "regs": dict(saved_regs)})

    def _snapshot(self) -> dict:
        return {
            "regs": dict(self.regs),
            "stack": list(self.stack),
            "arch_channel": self.mem.read(self.prog.symbols["arch_channel"], 8),
        }


def transfers(log: list[dict]) -> set[tuple[str, str, int]]:
    last: dict[int, dict] = {}
    out = set()
    for ev in log:
        if ev["kind"] == "write" and ev["committed"]:
            last[ev["slot"]] = ev
        elif ev["kind"] == "read" and ev["value"] is not None:
            write = last.get(ev["slot"])
            if write and write["func"] != ev["func"]:
                out.add((write["func"], ev["func"], ev["slot"]))
    return out
