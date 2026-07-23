# 部署指南 / Deployment Guide

## 设备分型 / Device Classes

目前实验结果显示，Walkman 可以分成两类部署路径：

Current experiments suggest two deployment paths:

1. A 系列低端/中端设备：stock kernel 会把写入的 tone table 应用到 CXD3778GF tone RAM。  
   A-series low/mid devices: the stock kernel applies the written tone table to CXD3778GF tone RAM.
2. ZX / WM 系列中高端设备：stock kernel 可能只更新驱动内存表，不自动刷新 tone RAM，需要 helper kernel module。  
   ZX / WM higher-end devices: the stock kernel may update only the in-memory table and require a helper kernel module to refresh tone RAM.

已验证：

Validated:

- NW-A50：直接写表有效。  
  NW-A50: direct table writes work.
- NW-ZX300A：需要 `cxd3778gf_tone_apply`。  
  NW-ZX300A: requires `cxd3778gf_tone_apply`.

## 通用准备 / Common Preparation

```bash
cd /home/neoncloud/walkman-tuning-guide
python3 -m pip install -r requirements.txt
```

Windows 用户应使用 PowerShell 和 Windows 版 `adb.exe`：

Windows users should use PowerShell with the Windows `adb.exe`:

```powershell
cd C:\path\to\walkman-tuning-guide
python -m pip install -r requirements.txt
$env:ADB = "C:\path\to\platform-tools\adb.exe"
```

Linux 用户应使用 bash 和 Linux 版 `adb`：

Linux users should use bash with the Linux `adb`:

```bash
cd /path/to/walkman-tuning-guide
python3 -m pip install -r requirements.txt
export ADB=/path/to/adb
```

备份：

Back up:

```bash
mkdir -p backups
"$ADB" shell 'cat /proc/icx_audio_cxd3778gf_data/tct' > backups/proc_tct.stock.bin
"$ADB" pull /system/usr/share/audio_dac/tc_1291.tbl backups/tc_1291.stock.tbl
```

如果只需要生成 all-target 自定义表，不需要把 Sony 原厂表放进仓库；可使用 identity base：

If you only need to generate an all-target custom table, do not add Sony stock tables to the repository; use an identity base:

```bash
python3 tools/cxd3778gf_tct_tool.py make-identity backups/tc_127x.tbl
```

## A 系列直接写入 / A-Series Direct Write

从 AutoEq 文本生成并写入 `sg` target：

Generate and write an AutoEq profile to target `sg`:

```bash
bash tools/apply_cxd3778gf_peq_adb.sh \
  --input my-autoeq.txt \
  --target sg \
  --filter-strategy best
```

Windows / PowerShell:

```powershell
.\scripts\install_tone_table.ps1 `
  -DeviceClass a `
  -Input my-autoeq.txt `
  -Target sg `
  -FilterStrategy best
```

还原：

Restore:

```bash
bash tools/apply_cxd3778gf_peq_adb.sh --restore --target sg
```

Windows / PowerShell:

```powershell
.\scripts\restore_stock_tone_table.ps1 -DeviceClass a -Target sg
```

## ZX / WM Helper Module 路径 / ZX / WM Helper Module Path

ZX300A 的关键问题是 `TYPE_Z` 路径不会自动执行 tone RAM reload。因此流程分两步：

The key ZX300A issue is that the `TYPE_Z` path does not automatically perform tone RAM reload. The flow has two steps:

1. 写完整 tone table 到 `/proc/icx_audio_cxd3778gf_data/tct`。  
   Write the full tone table to `/proc/icx_audio_cxd3778gf_data/tct`.
2. 通过 `/proc/cxd3778gf_tone_apply` 触发原始寄存器写入序列。  
   Trigger the stock register-write sequence through `/proc/cxd3778gf_tone_apply`.

构建和安装：

Build and install:

```bash
bash scripts/build_zx300_tone_apply.sh
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh
```

应用当前表：

Apply the current table:

```bash
bash experiments/reproduce/98_apply_cxd3778gf_tone_ram.sh
```

应用 Blessing 3 示例表：

Apply the Blessing 3 sample table:

```bash
bash experiments/reproduce/94_apply_bl3_rbj_refine_sensitive_zx300a_and_tone_ram.sh
```

Windows / PowerShell, after the helper module is loaded:

```powershell
.\scripts\install_tone_table.ps1 `
  -DeviceClass zx `
  -Table samples\autoeq\bl3-zx300a-rbj-refine-sensitive-all-targets\full-table\tc_127x.bl3-zx300a-rbj-refine-sensitive-all-targets.tbl
```

## 开机自动加载 / Autoload

autoload 会修改 `/system/bin/bootswitcher.sh`，模仿已有 mod 在开机时加载模块并应用 `/data/local/cxd3778gf_tone/auto_tct.tbl`。

Autoload edits `/system/bin/bootswitcher.sh`, following the existing mod pattern to load the module at boot and apply `/data/local/cxd3778gf_tone/auto_tct.tbl`.

安装：

Install:

```bash
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_autoload.sh
bash experiments/reproduce/98_set_cxd3778gf_tone_autoload_table.sh path/to/full-table.tbl
```

卸载：

Uninstall:

```bash
bash experiments/reproduce/99_uninstall_cxd3778gf_tone_apply_autoload.sh
```

## 目标 chunk / Target Chunks

已知 chunk 名称：

Known chunk names:

- `nh`: no headphone
- `ng`: normal amp, general headphone
- `nnw500`: normal amp, Sony NW500 case
- `nnw750`: normal amp, Sony NW750 case
- `nnc31`: normal amp, Sony NC31 case
- `sg`: S-Master amp, general headphone
- `snw500`: S-Master amp, Sony NW500 case
- `snw750`: S-Master amp, Sony NW750 case
- `snc31`: S-Master amp, Sony NC31 case

通常实验使用 `sg`，或者生成 all-target table，把所有 case 都替换成同一组滤波器。

Most experiments use `sg`, or generate an all-target table that replaces every case with the same filter set.

## 验证 / Verification

```bash
"$ADB" shell 'cat /proc/cxd3778gf_tone_apply 2>/dev/null || true'
"$ADB" shell 'dmesg | tail -80'
"$ADB" shell 'cat /proc/icx_audio_cxd3778gf_data/tct | md5sum'
```

如果没有明显听感变化，优先检查：

If there is no audible change, check:

- 表是否写入完整 `/proc/.../tct`，而不是只写了文件系统里的 `.tbl`。  
  Whether the full `/proc/.../tct` table was written, not only a filesystem `.tbl`.
- ZX / WM 上是否执行了 `echo apply` 或 `echo table 5`。  
  Whether `echo apply` or `echo table 5` was executed on ZX / WM.
- 当前输出路径是否真的使用目标 chunk，例如 `sg`。  
  Whether the current output path actually uses the target chunk, such as `sg`.
