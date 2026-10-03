# Weird Programs

Weird programs are microarchitectural weird machines that perform computation using Transient Architectural Execution. They are over two orders of magnitude faster than the existing [*weird gates*](https://github.com/joeywang4/Flexo).
For more information, please refer to [our paper](https://doi.ieeecomputersociety.org/10.1109/SP63933.2026.00066):

> Ping-Lun Wang, Fraser Brown, Riccardo Paccagnella, Eyal Ronen, Riad S. Wahby, Yuval Yarom.
> "Transient Architectural Execution: From Weird Gates to Weird Programs."
> IEEE Symposium on Security and Privacy (SP), 2026.

## What are weird programs?

Weird programs are microarchitectural weird machines (μWMs) that can perform computation purely using microarchitectural side effects.
Its computation happens in transient execution, and its states are stored in microarchitectural components.
This means that there is no visible architectural trace, and it is not possible to analyze its execution using a debugger.

Previously, μWMs adopt a circuit model and perform computation using small logic gates (*weird gates*) with limited computational ability.
We instead propose *weird programs* that adopt the **processor model**, which allows μWMs to perform computation using ISA instructions that are much more powerful than small logic gates through *transient architectural execution*.
This significantly improves the computational capabilities and the performance of μWMs, and it is a lot easier to implement μWMs following our construction as programmers can create a weird program similar to how they write a C++ program.

## Compile and run our code

We implement our weird programs using C++, and we use cmake, ninja, and LLVM 17 to build our code.
We provide a bash script ([`install.sh`](./install.sh)) to compile the code. 
Execute this script with the `--install-dep` argument to install the required dependencies (requires `sudo` permission).

After the execution of `install.sh`, the executables of our example weird programs (`aes.elf`, `search.elf`, and `simon.elf`) should be created in both `build/rerun1/` and `build/rerun3`.
The executables in `build/rerun3` will run the weird programs with 2-out-of-3 majority voting, and therefore they should have higher accuracy while with 3X runtime than the ones in `build/rerun1`, which only runs the weird program once without majority voting.

To reproduce our results, execute the bash script [`run.sh`](./run.sh), which will execute all our weird programs, with and without majority voting, and measure their median accuracy and runtime among 100 executions. It will also record the accuracy and runtime for each execution under the `logs/` directory.

## Code structure

Our code includes a software library that provides helpful functions to impelment a weird program and our example weird programs.

The [`include/`](./include/) and [`src/`](./src/) folders contain the source code of the software library, which allows weird programs to allocate BTB weird registers, access their values, and trigger transient execution.

The [`examples/`](./examples/) folder contains the source code of the example weird programs.
We implemented AES encryption ([`aes.cpp`](./examples/aes.cpp)), Simon encryption ([`simon.cpp`](./examples/simon.cpp)), and the binary search algorithm ([`search.cpp`](./examples/search.cpp)).

In addition, we provide a small example ([`gates.cpp`](./examples/gates.cpp)) that simply write and read a random value to and from a BTB weird register. 
This can be a great starting point to create a new weird program.
