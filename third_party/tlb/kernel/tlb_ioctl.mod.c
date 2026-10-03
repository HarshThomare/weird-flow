#include <linux/module.h>
#define INCLUDE_VERMAGIC
#include <linux/build-salt.h>
#include <linux/elfnote-lto.h>
#include <linux/export-internal.h>
#include <linux/vermagic.h>
#include <linux/compiler.h>

#ifdef CONFIG_UNWINDER_ORC
#include <asm/orc_header.h>
ORC_HEADER;
#endif

BUILD_SALT;
BUILD_LTO_INFO;

MODULE_INFO(vermagic, VERMAGIC_STRING);
MODULE_INFO(name, KBUILD_MODNAME);

__visible struct module __this_module
__section(".gnu.linkonce.this_module") = {
	.name = KBUILD_MODNAME,
	.init = init_module,
#ifdef CONFIG_MODULE_UNLOAD
	.exit = cleanup_module,
#endif
	.arch = MODULE_ARCH_INIT,
};

#ifdef CONFIG_MITIGATION_RETPOLINE
MODULE_INFO(retpoline, "Y");
#endif



static const struct modversion_info ____versions[]
__used __section("__versions") = {
	{ 0x79a7c8eb, "class_create" },
	{ 0x1d96a8fa, "device_create" },
	{ 0x122c3a7e, "_printk" },
	{ 0xad70ba05, "device_destroy" },
	{ 0x872a6a98, "class_unregister" },
	{ 0x2527e089, "class_destroy" },
	{ 0x6bc3fbc0, "__unregister_chrdev" },
	{ 0x40a0aafc, "__flush_tlb_all" },
	{ 0xf0fdf6cb, "__stack_chk_fail" },
	{ 0xbdfb6dbb, "__fentry__" },
	{ 0x5b8239ca, "__x86_return_thunk" },
	{ 0xdd8de019, "__register_chrdev" },
	{ 0x2f93810, "module_layout" },
};

MODULE_INFO(depends, "");


MODULE_INFO(srcversion, "7E6D0D81F7EC095B9598F27");
