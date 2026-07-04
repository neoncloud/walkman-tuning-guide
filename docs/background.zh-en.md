# 项目背景 / Project Background

## 起点 / Starting Point

Walkman 原生固件对不同耳机和不同输出路径有特殊调音。例如普通耳机、NW500、NW750、NC31 等 case 会对应不同的 tone-control table。这说明播放器内部存在一个比用户界面 10-band EQ 更底层的调音入口。

The stock Walkman firmware applies special tuning for different headphones and output paths. Cases such as general headphones, NW500, NW750, and NC31 map to different tone-control tables. This suggests that the player has a lower-level tuning entry point beyond the user-facing 10-band EQ.

`unknown321/wampy` 对 Walkman 音量表和滤波路径的研究提供了重要线索，尤其是表结构、固件路径和设备差异。Sony 发布的 GPL kernel source 则让 `cxd3778gf` codec 路径可以被直接审计。

The `unknown321/wampy` research on Walkman volume tables and filter paths provided important clues, especially around table layout, firmware paths, and device differences. Sony's GPL kernel source made the `cxd3778gf` codec path auditable.

## 源码线索 / Source Clues

在内核源码中，`cxd3778gf` / `cxd3774gf` 相关驱动暴露了几个关键事实：

In the kernel source, the `cxd3778gf` / `cxd3774gf` driver exposes several key facts:

- 驱动维护 tone-control table，并通过 proc 节点暴露。  
  The driver maintains tone-control tables and exposes them through proc nodes.
- 表会根据耳机和输出状态选择。  
  Tables are selected according to headphone and output state.
- A 系列路径会调用 `adjust_tone_control()` 把表写入 codec MEM。  
  The A-series path calls `adjust_tone_control()` to write the table into codec MEM.
- ZX300A 上存在 `TYPE_Z` 分支，stock 路径会跳过 tone RAM reload。  
  On ZX300A, the `TYPE_Z` path skips tone RAM reload in the stock flow.

这些线索说明：只修改文件表不一定足够。A 系列可以直接生效，但 ZX / WM 系列可能需要额外触发硬件写入。

These clues show that changing the table file alone is not always enough. A-series devices can apply the table directly, while ZX / WM devices may require an extra hardware-apply trigger.

## 实验验证 / Experiments

我们用非常夸张的滤波器验证 tone table 的真实作用：

We validated the table with intentionally exaggerated filters:

- 4 kHz +20 dB / -20 dB：变化非常明显。  
  4 kHz +20 dB / -20 dB: clearly audible.
- 低频 +20 dB / -20 dB：变化方向符合预期。  
  Low-frequency +20 dB / -20 dB: direction matched expectation.
- A50：直接写 proc table 即可生效。  
  A50: direct proc table writes worked.
- ZX300A：写 proc table 后仍需要 `cxd3778gf_tone_apply` 强制 apply。  
  ZX300A: proc table writes required `cxd3778gf_tone_apply` to force hardware apply.

这些实验支持“五级串联二阶 IIR”的核心模型。

These experiments support the core model of five cascaded second-order IIR sections.

## 构建结果 / Result

最终项目形成了三层：

The final project has three layers:

1. 表生成工具：从 AutoEq / PEQ / WAV target 生成 CXD3778GF tone table。  
   Table generation tools: AutoEq / PEQ / WAV target to CXD3778GF tone table.
2. 部署脚本：备份、写表、恢复、绘图和复现实验。  
   Deployment scripts: backup, write, restore, plot, and reproduce experiments.
3. ZX300A helper module：在 stock driver 不自动 apply 的机型上强制刷新 tone RAM。  
   ZX300A helper module: force-refresh tone RAM where the stock driver does not apply it automatically.

这个仓库的目标不是替代播放器系统 EQ，而是把 Walkman 固件本来就存在的 codec tone path 变成可理解、可复现、可定制的研究工具。

The goal is not to replace the player's system EQ, but to turn the existing Walkman codec tone path into an understandable, reproducible, and customizable research tool.
