CC = gcc
CFLAGS = -w -g -O1 -fno-ipa-icf -fno-delayed-branch \
	-fno-guess-branch-probability -falign-loops \
	-falign-functions=65536 -falign-labels -fcaller-saves \
	-fexpensive-optimizations -fno-if-conversion2 \
	-fno-if-conversion -fno-ipa-profile -fno-merge-constants \
	-fno-cse-follow-jumps -fno-cse-skip-blocks -fno-dse \
	-fno-dce -fno-tree-dse -fno-ipa-sra -fno-profile-arcs \
	-fno-gcse -fno-hoist-adjacent-loads -fomit-frame-pointer \
	-fno-cprop-registers -fno-rename-registers \
	-fno-schedule-insns -fno-schedule-insns2 \
	-fno-combine-stack-adjustments -fno-sched-spec -MMD
# CFLAGS += -DGATES_STATS
# CFLAGS += -fsanitize=address

SRCS = mm.c util.c math_util.c tlb_utils.c
SRCS_THRESHOLD = $(SRCS) threshold.c
SRCS_WINDOW = $(SRCS) test_window.c *.S

OBJS_THRESHOLD  = $(SRCS_THRESHOLD:.c=.o)
OBJS_WINDOW  = $(SRCS_WINDOW:.c=.o)

# Pattern rule for compiling .c to .o
%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

# Special rule for .S (assembly) files
%.o: %.S
	$(CC) $(CFLAGS) -c $< -o $@

test_window.o: test_window.c
	$(CC) $(CFLAGS) -c $< -o $@

.PHONY: all clean

all: threshold window

threshold: $(OBJS_THRESHOLD)
	$(CC) $(CFLAGS) $^ -o threshold.elf

window: $(OBJS_WINDOW)
	$(CC) $(CFLAGS) $^ -o test_window.elf

clean:
	rm -f *.o *.d *.elf
