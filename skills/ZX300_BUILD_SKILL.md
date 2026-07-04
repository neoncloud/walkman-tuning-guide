# ZX300 Tone Apply Build Skill

Use this skill when an AI agent or maintainer needs to build or adapt the `cxd3778gf_tone_apply` helper module for ZX300 / ZX / WM Walkman firmware.

当 AI agent 或维护者需要为 ZX300 / ZX / WM Walkman 固件编译或迁移 `cxd3778gf_tone_apply` helper module 时，使用本 skill。

## Goal / 目标

Build an out-of-tree kernel module that:

构建一个 out-of-tree 内核模块，使其：

- resolves stock `cxd3778gf` symbols with `kallsyms_lookup_name`;  
  通过 `kallsyms_lookup_name` 解析 stock `cxd3778gf` 符号；
- exposes `/proc/cxd3778gf_tone_apply`;  
  暴露 `/proc/cxd3778gf_tone_apply`；
- writes a selected 320-byte tone table into CXD3778GF MEM registers;  
  把选中的 320-byte tone table 写入 CXD3778GF MEM register；
- does not patch kernel text;  
  不 patch kernel text；
- does not write codec registers during `insmod`.  
  不在 `insmod` 阶段写 codec register。

## Required Inputs / 必要输入

- Sony GPL kernel source matching the target firmware.  
  与目标固件匹配的 Sony GPL kernel source。
- Prepared kernel tree with `.config`, `prepare`, and `scripts` completed.  
  已完成 `.config`、`prepare` 和 `scripts` 的 kernel tree。
- ARM hard-float cross compiler compatible with the stock kernel.  
  与 stock kernel 兼容的 ARM hard-float 交叉编译器。
- `vmlinux` / `System.map` / `/proc/kallsyms` if available.  
  如果可用，准备 `vmlinux`、`System.map` 或 `/proc/kallsyms`。
- Device readback from `/proc/icx_audio_cxd3778gf_data/tct`.  
  从设备读取的 `/proc/icx_audio_cxd3778gf_data/tct`。

## ZX300A Reference Symbols / ZX300A 参考符号

The tested ZX300A module used these runtime-resolved targets:

实测 ZX300A 模块使用以下运行时解析目标：

```text
present                              c0bc84d0
cxd3778gf_tone_control_table         c0f864a4
cxd3778gf_register_modify            c063ed28
cxd3778gf_register_write             c063ee2c
cxd3778gf_register_write_multiple    c063ec00
```

Do not assume these addresses are valid on another firmware. Reconfirm them from the matching kernel image or device.

不要假设这些地址在其他固件上有效。必须从匹配 kernel image 或设备重新确认。

## Adaptation Points / 迁移检查点

Before building for a non-ZX300A target, inspect:

迁移到非 ZX300A 目标前，检查：

- `struct cxd3778gf_status` layout from `<sound/cxd3778gf.h>`;  
  `<sound/cxd3778gf.h>` 中的 `struct cxd3778gf_status` 布局；
- `TYPE_A`, `TYPE_Z`, and any board-type constants;  
  `TYPE_A`、`TYPE_Z` 以及其他 board-type 常量；
- CXD3778GF register addresses and bit fields;  
  CXD3778GF register 地址和 bit field；
- `CODEC_RAM_WORD_SIZE`, `CODEC_RAM_SIZE`, table count, and chunk size;  
  `CODEC_RAM_WORD_SIZE`、`CODEC_RAM_SIZE`、table 数量和 chunk 大小；
- symbol availability for `present`;  
  `present` 符号是否可用；
- symbol availability for `cxd3778gf_tone_control_table`;  
  `cxd3778gf_tone_control_table` 符号是否可用；
- symbol availability for register write helpers;  
  register write helper 符号是否可用；
- whether the stock driver already applies tone RAM on the target board type.  
  stock driver 是否已经在目标 board type 上 apply tone RAM。

## Build / 编译

```bash
cd /home/neoncloud/walkman-tuning-guide

KDIR=/home/neoncloud/zx300-custom-kernel/work/kernel \
CROSS_COMPILE=/path/to/arm-linux-gnueabihf- \
bash scripts/build_zx300_tone_apply.sh
```

The expected output is:

预期输出：

```text
kernel_modules/cxd3778gf_tone_apply/cxd3778gf_tone_apply.ko
```

## Install / 安装

```bash
export ADB=/mnt/e/Downloads/platform-tools/adb.exe
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh
```

## Validate / 验证

```bash
"$ADB" shell 'cat /proc/cxd3778gf_tone_apply'
"$ADB" shell 'echo apply > /proc/cxd3778gf_tone_apply'
"$ADB" shell 'dmesg | tail -80'
```

Expected behavior:

预期行为：

- `insmod` only creates the proc node.  
  `insmod` 只创建 proc 节点。
- `cat /proc/cxd3778gf_tone_apply` reports `ready=1`.  
  `cat /proc/cxd3778gf_tone_apply` 显示 `ready=1`。
- writing `apply` or `table 5` logs `applied table=...`.  
  写入 `apply` 或 `table 5` 后 dmesg 出现 `applied table=...`。

## Autoload / 开机自动加载

If manual validation works, autoload can be installed:

手动验证通过后，可以安装 autoload：

```bash
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_autoload.sh
bash experiments/reproduce/98_set_cxd3778gf_tone_autoload_table.sh path/to/full-table.tbl
```

Autoload copies the module to `/system/lib/modules/`, patches `/system/bin/bootswitcher.sh`, and applies `/data/local/cxd3778gf_tone/auto_tct.tbl` at boot.

autoload 会把模块复制到 `/system/lib/modules/`，修改 `/system/bin/bootswitcher.sh`，并在开机时应用 `/data/local/cxd3778gf_tone/auto_tct.tbl`。

## Safety Rules / 安全规则

- Do not load the old kprobe trace module on production devices.  
  不要在日常设备上加载旧的 kprobe trace module。
- Do not patch kernel text for this flow.  
  本流程不要 patch kernel text。
- Do not write registers from module init.  
  不要在 module init 中写寄存器。
- Always provide a restore script before enabling autoload.  
  启用 autoload 前必须准备还原脚本。
- If the device reboots during `insmod`, stop and inspect `/proc/last_kmsg` before trying again.  
  如果 `insmod` 导致重启，停止操作并先检查 `/proc/last_kmsg`。
