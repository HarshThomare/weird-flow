# Flexo

This directory contains two Flexo variants:

| Directory | Description |
|---|---|
| `Flexo-DCache` | Uses the data cache as the covert channel (close to the original Flexo) |
| `Flexo-TLB` | Uses the TLB as the covert channel |

The `.patch` files contain the git diff against the original Flexo framework.

## Usage

Each variant directory contains a `run.sh` script for quick testing of circuits:

```bash
./run.sh <PATH_TO_CIRCUIT_FOLDER>
```

The circuit folder must contain a `build.sh` script that produces one or more `.elf` files. All generated `.elf` files are executed by `run.sh`.

Internally, `run.sh` calls `compile.sh` (in the same directory), which compiles a given `.ll` file into a `.ll` file with weird machine functions.

### Configuration constants (`compile.sh`)

| Constant | Description |
|---|---|
| `WR_HIT_THRESHOLD` | Threshold to distinguish TLB hit from miss |
| `DUAL_WM_MAX_INPUT` | Maximum number of inputs to a weird gate |
| `RET_WM_MUL_ROUNDS` | Number of `MUL` instructions used to open the transient window |
| `RET_WM_MUL_SIZE` | Bit-width of the `MUL` instructions |

### Example

```bash
./run.sh circuits/gates
```
