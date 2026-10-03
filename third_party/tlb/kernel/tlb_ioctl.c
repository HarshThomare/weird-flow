#include <asm/cacheflush.h>
#include <linux/cdev.h>
#include <linux/cpumask.h>
#include <linux/init.h>
#include <linux/ioctl.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/printk.h>
#include <linux/smp.h>
#include <asm/tlbflush.h>

#include "tlb_ioctl.h"

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Anonymous");
MODULE_DESCRIPTION("Make tlb operations available via ioctl");
MODULE_VERSION("0.1");

int major;
static struct class *tlb_class = NULL;
static struct device *tlb_device = NULL;

struct invpcid_desc {
    uint64_t pcid;    // PCID in low 12 bits; upper bits zero
    uint64_t address; // Linear address
};

static __always_inline uint16_t pcid(void) {
    uint64_t cr3;
    asm volatile("mov %%cr3, %0" : "=r"(cr3));
    return (uint16_t)(cr3 & 0xFFF); // low 12 bits are the PCID
}

/**
 * `invlpg` invalidates `addr` + all paging-structure caches
 */
static __always_inline void invlpg(void *addr) {
    asm volatile ("invlpg (%0)" : : "r"(addr) : "memory");
}

/**
 * type 0: flush only given address in pcid, equivalent to invlpg
 * type 1: flush all of pcid (address = 0)
 * type 2: flush all with globals (address, pcid = 0)
 * type 3: flush all except globals (address, pcid = 0)
 */
static __always_inline void invpcid(const uint64_t address, const uint64_t pcid, const uint64_t type) {
    const struct invpcid_desc desc = {
        .address = address,
        .pcid = pcid,
    };
    asm volatile("invpcid %0, %1"
                 :
                 : "m"(desc), "r"(type)
                 : "memory");
}

static void flush_tlb_pt_caches(void *addr) {
    invlpg(addr);
    __flush_tlb_all();
}

static void flush_tlb_no_pt_caches(void) {
    invpcid(0, 0, 2);
}

static void flush_tlb_addr_no_pt_caches(void *addr) {
    invpcid((uint64_t) addr, pcid(), 0);
}

static long tlb_ioctl(struct file *file, unsigned int cmd, unsigned long arg) {

    switch(cmd) {
        case IOCTL_FLUSH_TLB_PT_CACHES:
            flush_tlb_pt_caches((void *) arg);
            break;
        case IOCTL_FLUSH_TLB_NO_PT_CACHES:
            flush_tlb_no_pt_caches();
            break;
        case IOCTL_FLUSH_TLB_ADDR_NO_PT_CACHES:
            flush_tlb_addr_no_pt_caches((void *) arg);
            break;
        case IOCTL_FLUSH_TLB_INVLPG:
            invlpg((void *) arg);
            break;
        case IOCTL_FLUSH_NOTHING:
            break;
        default:
            break;
    }

    return 0;
}

static struct file_operations fops = {
    .unlocked_ioctl = tlb_ioctl,
};

static char *tlb_devnode(const struct device *dev, umode_t *mode) {
    if (!mode) {
        return NULL;
    }
    if (dev->devt == MKDEV(major, 0) ||
        dev->devt == MKDEV(major, 2)) {
        *mode = 0666;
    }
    return NULL;
}

static int __init tlb_module_init(void) {
    major = register_chrdev(0, TLB_DEVICE_NAME, &fops);
    if (major < 0) {
        printk(KERN_ALERT "TLB Device failed to register a major number\n");
        return major;
    }

    tlb_class = class_create(TLB_DEVICE_NAME);
    tlb_class->devnode = tlb_devnode;
    tlb_device = device_create(tlb_class, NULL, MKDEV(major, 0), NULL, TLB_DEVICE_NAME);
    pr_info("TLB Device registered\n");
    return 0;
}

static void __exit tlb_module_exit(void) {
    device_destroy(tlb_class, MKDEV(major, 0));
    class_unregister(tlb_class);
    class_destroy(tlb_class);
    unregister_chrdev(major, TLB_DEVICE_NAME);
    pr_info("TLB Device unregistered\n");
}

module_init(tlb_module_init);
module_exit(tlb_module_exit);
