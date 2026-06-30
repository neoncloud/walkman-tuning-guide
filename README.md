# Walkman终级调音指南

> English title: Walkman Ultimate Tuning Guide

本项目把 Sony Walkman A / ZX / WM 系列播放器中的 CXD3778GF tone table 调音路径整理成一个可复现的开源工程：从 AutoEq/PEQ 参数生成 CXD3778GF 可读取的五级二阶 IIR 系数表，再通过 ADB 或 ZX300 系列内核模块写入播放器。

This repository documents and packages an experimental Sony Walkman tuning path: convert AutoEq/PEQ filters into the CXD3778GF five-section biquad tone table, then deploy that table to supported Walkman players through ADB or a ZX300-family helper kernel module.

## Too Long; Don't Read / 快速安装

> 风险提示 / Risk: 这些步骤会写入播放器的音频调音表。请先备份原表；中高端机型还可能需要加载内核模块。你需要能承担恢复固件、重刷或手动清理模块的风险。

1. 解锁 ADB 调试 / Enable ADB debugging  
   参见 [ADB 解锁指南](docs/adb-unlock.zh-en.md)。低端 A 系列通常只需要 ADB root shell；ZX / WM 系列还需要确认内核行为。

2. 备份 stock table / Back up the stock tone table

   ```bash
   export ADB=/path/to/adb
   "$ADB" pull /system/usr/share/audio_dac/tc_1291.tbl backups/tc_1291.stock.tbl
   "$ADB" shell 'cat /proc/icx_audio_cxd3778gf_data/tct' > backups/proc_tct.stock.bin
   ```

3. 从 AutoEq 文本生成 PEQ blob / Generate a PEQ blob

   ```bash
   tools/autoeq_to_cxd3778gf_peq.py samples/sample-autoeq.txt out/sample.peq.tbl \
     --filter-strategy best --max-sections 5
   ```

4. A 系列直接写入目标 chunk / A-series direct proc write

   ```bash
   tools/apply_cxd3778gf_peq_adb.sh --input samples/sample-autoeq.txt --target sg \
     --filter-strategy best
   ```

5. ZX / WM 系列加载 helper module 后写入完整表 / ZX/WM helper-module path

   ```bash
   bash scripts/build_zx300_tone_apply.sh
   bash experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh
   bash experiments/reproduce/94_apply_bl3_rbj_refine_sensitive_zx300a_and_tone_ram.sh
   ```

6. 恢复 / Restore

   ```bash
   tools/apply_cxd3778gf_peq_adb.sh --restore --target sg
   bash experiments/reproduce/93_restore_zx300a_stock_tct_and_tone_ram.sh
   ```

## 简介 / Introduction

Sony Walkman A 系列、ZX 系列和 WM 系列中的多款 Linux/Android 机型共享相近的音频 codec 路径。本项目在 NW-A50 与 NW-ZX300A 的固件/内核材料中确认了 `cxd3778gf` 驱动，即 Sony CXD3778GF audio codec/DAC 路径。该驱动暴露 `/proc/icx_audio_cxd3778gf_data/{tct,tct_*}`，用于加载 tone-control table。

Many A-series, ZX-series, and WM-series Walkman players share a similar Sony audio codec path. In the tested A50 and ZX300A materials, the relevant kernel driver is `cxd3778gf`, which controls a Sony CXD3778GF audio codec/DAC path and exposes `/proc/icx_audio_cxd3778gf_data/{tct,tct_*}` for tone-control tables.

这个调音表的核心是一组级联的二阶 IIR 滤波器。每个输出/耳机 case 有一个 320-byte chunk；每个 chunk 分为两个 160-byte half，推定分别服务 44.1 kHz family 和 48 kHz family；每个 half 前 25 个 40-bit Q37 word 表示五个 biquad section：`b0, b1, b2, -a1, -a2`。

The table is essentially a cascade of second-order IIR filters. Each output/headphone case has one 320-byte chunk; each chunk has two 160-byte halves, currently interpreted as the 44.1 kHz and 48 kHz families. The first 25 signed 40-bit Q37 words in each half encode five biquad sections as `b0, b1, b2, -a1, -a2`.

本项目提供：

- AutoEq parametric EQ 到 CXD3778GF tone table 的转换工具。
- A 系列 stock kernel proc 节点直接写入流程。
- ZX300A `TYPE_Z` 路径的 `cxd3778gf_tone_apply` 内核模块，用于强制把已写入驱动内存的 table 刷入 CXD3778GF tone RAM。
- 可复现实验脚本、样例、研究记录和测量辅助工具。

This repository includes:

- AutoEq parametric-EQ to CXD3778GF table conversion tools.
- A direct stock-kernel proc-write flow for A-series players.
- A ZX300A `TYPE_Z` helper kernel module, `cxd3778gf_tone_apply`, that forces the in-memory table into CXD3778GF tone RAM.
- Reproducible scripts, samples, research notes, and measurement helpers.

## 详细安装 / Installation

### 1. 前置条件 / Prerequisites

- Linux or WSL.
- Python 3.8+ with `numpy`, `scipy`, and `matplotlib` for fitting/plotting tools.
- `adb` with root shell access to the Walkman.
- For ZX300A helper modules: a prepared matching Sony 3.10.26 kernel tree and an ARM hard-float cross toolchain.

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

### 2. 解锁 ADB / Unlock ADB

ADB 解锁需要修改官方固件安装脚本，让播放器在安装固件时开启调试入口。详见：

See the dedicated guide:

- [docs/adb-unlock.zh-en.md](docs/adb-unlock.zh-en.md)
- helper script: [scripts/patch_firmware_adb_unlock.sh](scripts/patch_firmware_adb_unlock.sh)

### 3. A 系列写入 / A-Series Deployment

A50 实测可直接写入 `/proc/icx_audio_cxd3778gf_data/tct_*`，并通过 readback 验证。通常 `sg` 是普通平衡/耳放路径下的 general headphone table。

```bash
tools/apply_cxd3778gf_peq_adb.sh --input my-autoeq.txt --target sg --filter-strategy best
```

### 4. ZX / WM 系列写入 / ZX/WM Deployment

ZX300A stock driver 在 `TYPE_Z` 上会跳过 `adjust_tone_control()` 的 tone RAM 写入。流程是先写完整 `/proc/.../tct`，再通过 `cxd3778gf_tone_apply` 模块手动执行 stock MEM 写入序列。

```bash
bash scripts/build_zx300_tone_apply.sh
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh
bash experiments/reproduce/98_apply_cxd3778gf_tone_ram.sh
```

迁移到其他 ZX / WM 机型时，请先阅读：

- [ZX300 构建 Skill](docs/ZX300_BUILD_SKILL.md)
- [部署指南](docs/deployment.zh-en.md)

## 算法原理 / Algorithm

PEQ 到调音表的转换分三步：

1. Parse AutoEq filters: `PK`, `LS`, `HS`, preamp, frequency, gain, Q.
2. Convert each PEQ filter to a normalized RBJ biquad at both 44.1 kHz and 48 kHz.
3. Encode each coefficient as signed 40-bit big-endian Q37 and append Sony's `sum32/xor32` checksum.

当 AutoEq 提供超过五段滤波器时，硬件容量不足。本项目提供多种裁剪策略：

- `first`: 保持输入顺序取前五段。
- `largest`: 取绝对增益最大的五段。
- `wide`: 优先低 Q / shelf 这类宽影响滤波器。
- `greedy`: 贪心降低全响应 RMS 误差。
- `best`: 枚举可行组合，选择 RMS 误差最低的一组。

For full-waveform targets, the fitting tools can also optimize five stable SOS sections against a minimum-phase WAV target. The safest baseline remains RBJ-style filters; the Torch SOS optimizer is more flexible but must constrain pole radius, section peak, prefix peak, and Q37 coefficient range.

More detail:

- [docs/algorithm.zh-en.md](docs/algorithm.zh-en.md)
- [docs/methods.zh.md](docs/methods.zh.md)

## 背景与构建 / Background and Build

固件源码与前人研究共同暗示了这条路径：

- Wampy 的滤波链研究指出 Walkman 的滤波器由 `libSoundServiceFw.so` 组织，不同机型/固件更多是软件锁和表数据差异。
- Sony kernel driver `sound/soc/codecs/cxd3774gf/cxd3774gf.c`/`cxd3778gf` 相关符号暴露了 tone-control table、`/proc/icx_audio_cxd3778gf_data/tct` 和 codec MEM 写入路径。
- A50 上 `tc_1291.tbl[:-8]` 与 `/proc/.../tct` 完全对应，9 个 chunk 分别映射 `tct_nh/ng/nnw500/.../sg/...`。
- ZX300A 上只读状态模块显示 `board_type=TYPE_Z`，stock 路径跳过 tone RAM reload；因此需要 helper module。

The project evolved from raw firmware/table dumps, then table layout identification, audible probes, Q37 coefficient modeling, AutoEq conversion, constrained IIR fitting, and finally the ZX300A helper module.

## 致谢、版权与 License / Credits, Copyright, License

感谢 / Thanks:

- AutoEq community for headphone correction data and methodology.
- Wampy and Walkman custom-firmware researchers for filter-chain and table-path clues.
- Sony GPL kernel source releases, which made the `cxd3778gf` path auditable.
- All testers willing to risk time, ears, and recovery procedures on real hardware.

Licensing:

- Source code in `tools/`, `scripts/`, `experiments/`, and `kernel_modules/` is licensed under **GPL-3.0-or-later**. GPL does not prohibit commercial use; it requires source availability and copyleft compliance.
- Documentation, articles, and research notes in `README.md` and `docs/` are licensed under **CC BY-NC-ND 4.0**: attribution required, non-commercial use only, no modified redistribution.
- Device firmware, Sony binaries, stock tone tables, and third-party datasets are not included. You must obtain them legally from your own device or upstream source.

本项目按原样提供，不承诺适配任何设备，也不承担刷机、损坏设备、听力风险或数据丢失责任。

This project is provided as-is, with no warranty and no guarantee of device compatibility or safety.
