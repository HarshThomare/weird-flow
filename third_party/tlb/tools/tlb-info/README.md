# TLB Info

Reads detailed TLB topology from a modern Intel CPU using **CPUID leaf 0x18**, which provides richer information than the legacy leaf 0x2. Reports the number of entries, sets, ways, page size support, and cache type for each TLB level.

> **Note:** Leaf 0x18 is only available on processors that signal it via leaf 0x2. The script will print an error and exit if the CPU does not support it.

## Example output

```
L1D    4K             TLB(load):   64 entries,   64 sets,   full, 0 partitions,  1 shared
L1D    4K             TLB(store):  32 entries,   32 sets,   4 way, 0 partitions, 1 shared
L1I    4K+2MB+4MB     TLB:         128 entries,  128 sets,  full, 0 partitions,  1 shared
L2I+D  4K+2MB+1GB     TLB:         2048 entries, 2048 sets, full, 0 partitions,  1 shared
```

## Usage

Install dependencies and run:

```bash
pip install -r requirements.txt
python3 tlb-info.py
```