mod_ret_addr:
	movq	$15001, %rcx                    # imm = 0x3A99
	movq	$60221, %rax
	movq	$10664, %rdx
	divw	%cx # long division
	... # repeats $RET_WM_DIV_ROUNDS times

	# adds padding of NOPs after weird computations to return address (e.g. 512)
	addq	%rdx, (%rsp)
	retq
# XOR Gate
	.globl	__DualGate__2_1_xor           # -- Begin function __DualGate__2_21_xxx
	.p2align	4, 0x90
	.type	__DualGate__2_1_xor,@function
__DualGate__2_1_xor:                  # @__DualGate__2_1_xxx
	call mod_ret_addr										# trigger speculation with long running task
	# load all values
	movzbq (in1_0), in1_0
	movzbq (in1_1), in1_1
	movzbq (in2_0), in2_0
	movzbq (in2_1), in2_1
	# xor computation:

	# out_1 = in2_1 & in1_0
	lea (out_1,in1_0), %r10
	mov (%r10, in2_1), %r10b
	# out_1 = in2_0 & in1_1
	lea (out_1, in1_1), %r10
	mov (%r10, in2_0), %r10b

	# out_0 = in2_0 & in1_0
	lea (out_0,in1_0), %r10
	mov (%r10, in2_0), %r10b
	# out_0 = in2_1 & in1_1
	lea (out_0,in1_1), %r10
	mov (%r10, in2_1), %r10b
	
# AND Gate
	.globl	__DualGate__2_1_and           # -- Begin function __DualGate__2_1_xxx
	.p2align	4, 0x90
	.type	__DualGate__2_1_and,@function
__DualGate__2_1_and:                  # @__DualGate__2_1_xxx
	call mod_ret_addr										# trigger speculation with long running task
	# load all values
	movzbq (in1_0), in1_0
	movzbq (in1_1), in1_1
	movzbq (in2_0), in2_0
	movzbq (in2_1), in2_1
	# And computation:

	# out_1 = in1_0 & in2_0
	lea (out_1,in2_0), %r10
	mov (%r10, in1_0), %r10b

	# out_0 = in1_1
	lea (out_0, in1_1), %r10
	# out_0 = in2_1
	lea (out_0,in2_1), %r10

# Some 4->1 gate
	.globl	__DualGate__4_1_38505           # -- Begin function __DualGate__4_1_38505
	.p2align	4, 0x90
	.type	__DualGate__4_1_38505,@function
__DualGate__4_1_38505:                  # @__DualGate__4_1_38505
	.cfi_startproc
# %bb.0:                                # %entry
# prepare function by pushing registers
	pushq	%r15
	.cfi_def_cfa_offset 16
	pushq	%r14
	.cfi_def_cfa_offset 24
	pushq	%r13
	.cfi_def_cfa_offset 32
	pushq	%r12
	.cfi_def_cfa_offset 40
	pushq	%rbx
	# debugging boilerplate
	.cfi_def_cfa_offset 48
	.cfi_offset %rbx, -48
	.cfi_offset %r12, -40
	.cfi_offset %r13, -32
	.cfi_offset %r14, -24
	.cfi_offset %r15, -16
	# put all parameters into registers (rbx, r11, r9, r8, r13, r12, r15, r14)
	movq	%r9, %rbx
	movq	%r8, %r11
	movq	%rcx, %r9
	movq	%rdx, %r8
	movq	72(%rsp), %r13
	movq	64(%rsp), %r12
	movq	56(%rsp), %r15
	movq	48(%rsp), %r14
	#APP
	# call long running function (many div)
	callq	mod_ret_addr
	# load inputs -> simple and of values
	movzbq	(%rdi), %rdi
	movzbq	(%rsi), %rsi
	movzbq	(%r8), %r8
	movzbq	(%r9), %r9
	movzbq	(%r11), %r11
	movzbq	(%rbx), %rbx
	movzbq	(%r14), %r14
	movzbq	(%r15), %r15
	# 
	leaq	(%r13,%rdi), %r10
	addq	%r11, %r10
	addq	%r14, %r10
	movb	256(%r10,%r8), %r10b
	leaq	(%r13,%rdi), %r10
	addq	%rbx, %r10
	addq	%r15, %r10
	movb	256(%r10,%r8), %r10b
	leaq	(%r13,%rdi), %r10
	addq	%r11, %r10
	addq	%r15, %r10
	movb	256(%r10,%r9), %r10b
	leaq	(%r13,%rdi), %r10
	addq	%rbx, %r10
	addq	%r14, %r10
	movb	256(%r10,%r9), %r10b
	leaq	(%r13,%rsi), %r10
	addq	%r11, %r10
	addq	%r15, %r10
	movb	256(%r10,%r8), %r10b
	leaq	(%r13,%rsi), %r10
	addq	%rbx, %r10
	addq	%r14, %r10
	movb	256(%r10,%r8), %r10b
	leaq	(%r13,%rsi), %r10
	addq	%r11, %r10
	addq	%r14, %r10
	movb	256(%r10,%r9), %r10b
	leaq	(%r13,%rsi), %r10
	addq	%rbx, %r10
	addq	%r15, %r10
	movb	256(%r10,%r9), %r10b
	leaq	(%r12,%rdi), %r10
	addq	%r11, %r10
	addq	%r15, %r10
	movb	256(%r10,%r8), %r10b
	leaq	(%r12,%rdi), %r10
	addq	%rbx, %r10
	addq	%r14, %r10
	movb	256(%r10,%r8), %r10b
	leaq	(%r12,%rdi), %r10
	addq	%r11, %r10
	addq	%r14, %r10
	movb	256(%r10,%r9), %r10b
	leaq	(%r12,%rdi), %r10
	addq	%rbx, %r10
	addq	%r15, %r10
	movb	256(%r10,%r9), %r10b
	leaq	(%r12,%rsi), %r10
	addq	%r11, %r10
	addq	%r14, %r10
	movb	256(%r10,%r8), %r10b
	leaq	(%r12,%rsi), %r10
	addq	%rbx, %r10
	addq	%r15, %r10
	movb	256(%r10,%r8), %r10b
	leaq	(%r12,%rsi), %r10
	addq	%r11, %r10
	addq	%r15, %r10
	movb	256(%r10,%r9), %r10b
	leaq	(%r12,%rsi), %r10
	addq	%rbx, %r10
	addq	%r14, %r10
	movb	256(%r10,%r9), %r10b

	#NO_APP
	#APP
	.byte	144 # 0x90 -> NOP
	... # repeats 512 times

	#NO_APP
	popq	%rbx
	.cfi_def_cfa_offset 40
	popq	%r12
	.cfi_def_cfa_offset 32
	popq	%r13
	.cfi_def_cfa_offset 24
	popq	%r14
	.cfi_def_cfa_offset 16
	popq	%r15
	.cfi_def_cfa_offset 8
	retq
