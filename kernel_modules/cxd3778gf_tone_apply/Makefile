obj-m += cxd3778gf_tone_apply.o

KDIR ?= /tmp/zx300-lkm-fresh-20260623/kernel
CROSS_COMPILE ?= /tmp/zx300-linaro-good/gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf/bin/arm-linux-gnueabihf-

all:
	$(MAKE) -C $(KDIR) M=$(PWD) ARCH=arm CROSS_COMPILE=$(CROSS_COMPILE) modules

strip: all
	$(CROSS_COMPILE)strip --strip-unneeded cxd3778gf_tone_apply.ko

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) ARCH=arm CROSS_COMPILE=$(CROSS_COMPILE) clean
