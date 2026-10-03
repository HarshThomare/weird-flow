CXX = clang-17
CXXFLAGS = -fno-discard-value-names -O1 -fno-inline-functions -S -emit-llvm

SOURCES = ALU.cpp
TARGETS = $(SOURCES:.cpp=.ll)

SIZE_VALUES ?= 8 9 10 11 12 14 16 24 32 34 36 40 48
ALUx_LL = $(foreach S,$(SIZE_VALUES),ALU$(S).ll)

all: $(TARGETS) $(ALUx_LL)

%.ll: %.cpp
	$(CXX) $(CXXFLAGS) $< -o $@

ALU%.ll: ALUx.cpp
	sed "s/parameter SIZE = [0-9]\+/parameter SIZE = $(*)/" ALUx.v > ALU$(*).v  && \
	$(CXX) $(CXXFLAGS) -DSIZE=$* $< -o $@

clean-v:
	find . -maxdepth 1 -type f -regextype posix-extended -regex './ALU[0-9]+' -delete

clean: clean-v
	$(RM) $(TARGETS) $(ALUx_LL) *.ll *.elf ALU+.v
