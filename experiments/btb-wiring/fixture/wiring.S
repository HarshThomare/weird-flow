/* Hand-scheduled TAE-style program.
   driver writes BTB slots 0 and 1, clobbers architectural state, then
   calls weird. weird, inside a ret-hijack window, reads those slots,
   reads slot 0 a second time (non-destructive), and writes the sum to
   slot 2 and the echoed input to slot 4. driver then reads 2 and 4.
   No architectural register or the arch_channel global carries the
   inputs across the call.

   driver_neg / weird_neg share the substrate but not a slot: the write
   is slot 0 and the read is slot 7. */

    .section .text

    .global driver
    .type driver, @function
driver:
    lea decode_table(%rip), %rax
    movzwl %di, %edx
    imul $5, %edx, %edx
    add %rax, %rdx
    mov %rdx, %rbx
    call jmpreg0

    lea decode_table(%rip), %rax
    movzwl %si, %edx
    imul $5, %edx, %edx
    add %rax, %rdx
    mov %rdx, %rbx
    call jmpreg1

    xor %eax, %eax
    xor %ebx, %ebx
    xor %ecx, %ecx
    xor %edx, %edx
    xor %edi, %edi
    xor %esi, %esi
    xor %r8d, %r8d
    xor %r9d, %r9d
    xor %r10d, %r10d
    xor %r11d, %r11d
    xor %r12d, %r12d
    xor %r13d, %r13d
    xor %r14d, %r14d
    xor %r15d, %r15d
    movq $0, arch_channel(%rip)
    call oracle_probe
    call weird

    xor %eax, %eax
    lea dummy_delay(%rip), %rbx
    call jmpreg2
    mov %eax, %r12d

    xor %eax, %eax
    lea dummy_delay(%rip), %rbx
    call jmpreg4
    mov %r12d, %eax
    ret
    .size driver, .-driver

    .global weird
    .type weird, @function
weird:
    lea end_weird(%rip), %rdi
    call create_window

    xor %eax, %eax
    lea dummy_delay(%rip), %rbx
    call jmpreg0
    mov %eax, %r12d

    xor %eax, %eax
    lea dummy_delay(%rip), %rbx
    call jmpreg0
    mov %eax, %r13d

    xor %eax, %eax
    lea dummy_delay(%rip), %rbx
    call jmpreg1
    add %r13d, %eax
    mov %eax, %r14d

    lea decode_table(%rip), %rax
    movzwl %r14w, %edx
    imul $5, %edx, %edx
    add %rax, %rdx
    mov %rdx, %rbx
    call jmpreg2

    lea decode_table(%rip), %rax
    movzwl %r13w, %edx
    imul $5, %edx, %edx
    add %rax, %rdx
    mov %rdx, %rbx
    call jmpreg4

end_weird:
    nop
    ret
    .size weird, .-weird

    .global driver_neg
    .type driver_neg, @function
driver_neg:
    lea decode_table(%rip), %rax
    movzwl %di, %edx
    imul $5, %edx, %edx
    add %rax, %rdx
    mov %rdx, %rbx
    call jmpreg0
    xor %eax, %eax
    xor %ebx, %ebx
    xor %edi, %edi
    call weird_neg
    xor %eax, %eax
    lea dummy_delay(%rip), %rbx
    call jmpreg7
    ret
    .size driver_neg, .-driver_neg

    .global weird_neg
    .type weird_neg, @function
weird_neg:
    lea end_neg(%rip), %rdi
    call create_window
    xor %eax, %eax
    lea dummy_delay(%rip), %rbx
    call jmpreg7
end_neg:
    nop
    ret
    .size weird_neg, .-weird_neg

    .global _start
    .type _start, @function
_start:
    mov $0x11, %edi
    mov $0x22, %esi
    call driver
    mov $0x11, %edi
    call driver_neg
    hlt
    .size _start, .-_start

    .section .note.GNU-stack,"",@progbits
