# Kernel Module
This directory holds the kernel module that is needed for the Experiments.

The kernel module provides an ioctl interface to invalidate tlb entries via instructions that only can be executed from kernel mode.

### Build
Build the kernel module via `make`
and insert it via `insmod tlb_ioctl.ko`.
