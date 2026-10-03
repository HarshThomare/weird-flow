#include <linux/ioctl.h>

#define TLB_DEVICE_NAME "tlb_device"
#define TLB_DEVICE_NAME_FULL "/dev/tlb_device"
#define IOCTL_FLUSH_TLB_PT_CACHES _IOW(43, 0, void *)
#define IOCTL_FLUSH_TLB_NO_PT_CACHES _IOW(43, 1, void *)
#define IOCTL_FLUSH_TLB_ADDR_NO_PT_CACHES _IOW(43, 2, uint64_t *)
#define IOCTL_FLUSH_TLB_INVLPG _IOW(43, 3, uint64_t *)
#define IOCTL_FLUSH_NOTHING _IOW(43, 4, uint64_t *)
