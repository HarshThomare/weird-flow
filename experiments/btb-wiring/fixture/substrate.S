/* BTB weird-register substrate, same contract as third_party/tae:
   include/WeirdStates/IndirectJmp.h and src/WeirdStates/IndirectJmp.cpp.
   jmpregN is `jmp *%rbx` on a 32-byte stride (ALIGN).
   decode_table entries are `movw $value, %ax; ret` on a 5-byte stride
   (TBL_STRIDE). A write trains the slot with a table pointer. A read
   leaves rbx pointing elsewhere and relies on the trained target.
   256 entries cover the values this kill test actually moves. */

    .section .text
    .global jmpreg0
    .type jmpreg0, @function

    .macro GEN_JMP
    .global jmpreg\@
    .type jmpreg\@, @function
    .align 32
jmpreg\@:
    jmp *%rbx
    .size jmpreg\@, .-jmpreg\@
    .endm

    .rept 16
    GEN_JMP
    .endr

    .global decode_table
    .type decode_table, @function
    .align 4096
decode_table:
    value = 0
    .rept 256
    movw $value, %ax
    ret
    value = value + 1
    .endr
    .size decode_table, .-decode_table

    /* Non-table target used as the architectural destination of a read.
       A BTB read must not execute this; doing so yields the sentinel. */
    .global dummy_delay
    .type dummy_delay, @function
dummy_delay:
    mov $0xFFFF, %eax
    ret
    .size dummy_delay, .-dummy_delay

    .set _Z7jmpreg0v, jmpreg0
    .global _Z7jmpreg0v
    .set _Z12decode_tablev, decode_table
    .global _Z12decode_tablev

    .section .data
    .global arch_channel
    .align 8
arch_channel:
    .quad 0

    .section .text
    .global opaque_zero
    .type opaque_zero, @function
opaque_zero:
    movl $0, %eax
    ret
    .size opaque_zero, .-opaque_zero

    .global oracle_probe
    .type oracle_probe, @function
oracle_probe:
    ret
    .size oracle_probe, .-oracle_probe

    .global create_window
    .type create_window, @function
/* Same gadget as WM::createWindow in TransientWindows/RetBased.cpp:
   overwrite the return address, then ret. The architectural target is
   the slow destination; the bytes after the call are the transient body. */
create_window:
    mov %rdi, (%rsp)
    ret
    .size create_window, .-create_window

    .section .note.GNU-stack,"",@progbits
