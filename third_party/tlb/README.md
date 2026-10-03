# CTRL-ALT-TLB Artifacts

## Test Machines

| Name | CPU | OS |
|---|---|---|
| Meteorlake | Intel Ultra 7 155H | Ubuntu 24.04.3 |
| Kabylake | Intel Core i5-7260U | Ubuntu 24.04.3 |

## Repository Structure

| Directory | Description |
|---|---|
| [`kernel/`](kernel/) | Kernel module providing an ioctl interface to invalidate TLB entries (requires ring-0 privileges) |
| [`Flexo/`](Flexo/) | Flexo framework variants for TLB-based weird-machine execution (DCache and TLB covert channels) |
| [`tools/`](tools/) | Tools for transient window and TLB exploration (`tlb-info`, `tlb-test`) |

## Setup

### Kernel Module

The kernel module is required for all experiments. Build and insert it with root privileges:

```bash
cd kernel/
make
insmod tlb_ioctl.ko
```

To remove the module:

```bash
rmmod tlb_ioctl
```
