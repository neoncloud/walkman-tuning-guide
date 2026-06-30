# CXD3778GF PEQ 方法与实验记录

本文档记录 Walkman A50 / ZX300 系列 `cxd3778gf` tone table 的当前理解、拟合算法和复现方式。所有路径默认位于 WSL：

```bash
cd /home/neoncloud/zx300-peq-research
```

## 目标

原生固件只暴露 10-band EQ，不足以直接接入 AutoEq 的完整耳机校正。当前路线不是在音频 PCM 层做卷积，而是利用 CXD3778GF 已有的 tone RAM，把 AutoEq 的目标频响拟合成硬件可执行的 IIR biquad 级联。

当前推荐路径：

1. 使用 AutoEq 的 minimum-phase WAV 作为目标幅频响应。
2. 拟合 5 个稳定二阶 IIR section。
3. 写入完整 `tc_1291.tbl`，同时替换 `ng` 和 `sg` chunk。
4. 通过完整 `/proc/icx_audio_cxd3778gf_data/tct` 写入触发硬件 reload。

## tone table 结构

`tc_1291.tbl` 是 2888 字节：

- 前 2880 字节是 9 个 tone chunk。
- 最后 8 字节是 Sony checksum：`sum32` 和 `xor32`，小端。
- 每个 chunk 是 320 字节。
- 每个 chunk 分成两个 160 字节 half，推断分别对应 44.1k family 和 48k family。
- 每个 half 有 32 个 signed 40-bit big-endian Q37 word。
- 前 25 个 word 是 5 个 biquad：

```text
b0, b1, b2, -a1, -a2
```

- 后 7 个 word 当前视为 padding / reserved。

我们用 4 kHz `+20 dB / -20 dB` 和低频 `+20 dB / -20 dB` 验证前 5 个 biquad：听感变化非常明显，且方向符合预期。我们也把第 6 个 biquad 写入 words 25..29 做容量探测，`1 kHz +12 dB`、`4 kHz +/-20 dB` 均未产生可闻变化。因此目前实现只使用 5 个 section。

## 写入路径

有两个容易混淆的 proc 写法：

- 写 `tct_ng` / `tct_sg`：readback 会变化，但不一定触发当前硬件链路 reload。
- 写完整 `tct`：写入 2888 字节完整 table，会触发硬件 reload，是当前听感实验使用的路径。

恢复 stock：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/90_restore_stock_tct.sh
```

应用当前推荐 Blessing 3 表：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/91_apply_best_torch_sgd_5sos.sh
```

## WAV 目标

当前 Blessing 3 目标文件：

```text
samples/autoeq/blessing3-mp48000/source/Moondrop Blessing 3 minimum phase 48000Hz.wav
```

这个 WAV 是耳机校正用 minimum-phase impulse response。我们读取冲击响应，做 FFT，取幅度，转换为 dB，并在 20 Hz 到 20 kHz 的对数频率网格上作为拟合目标。

## 算法路线

### RBJ 5 段基线

脚本：

```text
tools/fit_cxd3778gf_iir_to_wav.py
```

方法：

- 只使用常见 RBJ EQ 类型：`LSC`、`PK`、`HSC`。
- 尝试多个 5 段拓扑，例如 `LSC,PK,PK,PK,HSC`。
- 使用 `least_squares` 最小化 dB 误差。
- 低于 35 Hz 和高于 10 kHz 略降权，减少极端边缘频点支配优化。
- 输出 raw chunk、带 checksum chunk、完整 table、SVG/CSV 曲线和 JSON metadata。

特点：

- 安全、可解释，适合作为基线。
- 对 Blessing 3 WAV 的拟合误差约 `0.39 dB RMS`。
- 因为只能使用固定 EQ 形状，精度不如自由 SOS 优化。

复现：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/10_blessing3_rbj_wav_fit.sh
```

### Torch 5-SOS 约束优化

脚本：

```text
tools/fit_cxd3778gf_torch_sos_to_wav.py
```

方法：

- 直接优化 5 个二阶 section。
- section 使用极点/零点半径和角度参数化，天然保持实系数共轭对。
- 用半径上限约束稳定性和最小相位倾向。
- 损失函数拟合 log-magnitude / dB 响应。
- 加入 section peak 和 prefix peak 惩罚，避免“巨大中间增益互相抵消”导致噪声或滋滋声。
- 使用多随机起点，取误差和安全指标综合最优的结果。

关键约束：

- `--max-pole-radius 0.95`
- `--max-section-peak-db 8.0`
- `--max-prefix-peak-db 4.0`
- `--section-peak-weight 0.5`
- `--prefix-peak-weight 1.0`

特点：

- 当前最推荐的 Blessing 3 方案。
- 比 RBJ 自由度更高，但通过约束避免早期 IIRNet-style 实验出现的噪声。
- 需要 torch/CUDA；默认 Python 是 `/home/neoncloud/miniconda3/envs/pytorch/bin/python`。

复现：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/20_blessing3_torch_sgd_5sos.sh
```

### 4-SOS + pre-gain

方法：

- 保留一个 biquad 位置模拟 pre-gain。
- 只用 4 个真实 SOS 拟合频响。

结论：

- 指标和听感都弱于完整 5-SOS。
- 可以作为对照，不作为推荐方案。

复现：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/21_blessing3_torch_sgd_4sos_pregain.sh
```

### IIRNet-style / IIRNet 8th-order

方法：

- 调研并尝试 IIRNet 相关思路。
- 早期自由 SOS 拟合能得到很低 RMS，但 section 内部峰值过高，设备上出现严重噪音和滋滋声。
- 后续加入约束后变安全，但精度下降。
- IIRNet 8th-order + pre-gain 作为对照实验保留。

结论：

- “只看总频响误差”是不够的。
- 对硬件 table 来说，section peak、prefix peak、极点半径和 Q37 系数量级同样重要。

复现：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/30_blessing3_iirnet8_pregain.sh
```

### Yule-Walker / invfreq 类方法

方法：

- 从目标幅频曲线设计 10 阶 IIR。
- 再拆成 5 个 biquad 写入 table。

结论：

- 作为传统 DSP 对照有价值。
- 当前 Blessing 3 结果不如受约束 Torch 5-SOS。

复现：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/40_blessing3_yulewalk_order10.sh
```

## 图表输出

每个拟合脚本都应输出图表，至少包含：

- target 频响。
- fitted IIR 频响。
- error = fitted - target。

RBJ 脚本输出示例：

```text
samples/autoeq/blessing3-rbj-refactor/plots/blessing3-rbj-refactor.svg
samples/autoeq/blessing3-rbj-refactor/plots/blessing3-rbj-refactor.csv
```

Torch / IIRNet / Yule-Walker 脚本输出在各自目录的 `plots/` 下。

## 复现规范

以后每个实验都必须同时提交：

1. 一个 `experiments/reproduce/*.sh` 脚本。
2. 固定输出目录。
3. metadata JSON。
4. 拟合图或响应图。
5. 是否写设备的说明。

生成类脚本不允许自动写设备；写设备必须使用 `90_` 之后的脚本，并在文件头注释中说明。

完整复现当前推荐生成结果：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/20_blessing3_torch_sgd_5sos.sh
```

完整复现 RBJ 安全基线：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/10_blessing3_rbj_wav_fit.sh
```

## 当前推荐

日常继续实验时优先使用 Torch 5-SOS 受约束优化结果：

```text
samples/autoeq/blessing3-torch-sgd-5sos/full-table/tc_1291.blessing3-torch-sgd-5sos-ng-sg.tbl
```

如果要做“算法是否正确”的 sanity check，优先使用 RBJ 脚本，因为它简单、可解释、容易排错。

## ZX300A tone table 通路结论

2026-06-28 在 ZX300A 实机上用只读内核模块 `cxd3778gf_state` 验证：

- 模块路径：`tools/kernel_modules/cxd3778gf_state/`。
- 编译脚本：`experiments/reproduce/71_build_cxd3778gf_state_module.sh`。
- 安装脚本：`experiments/reproduce/97_install_cxd3778gf_state_module.sh`。
- 读取脚本：`experiments/reproduce/98_read_cxd3778gf_state.sh`。
- 卸载脚本：`experiments/reproduce/99_uninstall_cxd3778gf_state_module.sh`。

关键输出：

```text
board_type=2(TYPE_Z/zx-series)
output_device=1(headphone)
headphone_amp=2(smaster-btl)
headphone_type=3(other)
jack_status_se=0(none)
tone_control_hw_apply=0
tone_control_hw_apply_reason=adjust_tone_control_returns_before_ram_write_on_non_TYPE_A
would_select_tone_table=5(tct_sg/samp_general_hp)
```

解释：

- `adjust_tone_control()` 源码开头检查 `present.board_type != TYPE_A` 时直接返回。
- ZX300A 当前是 `TYPE_Z`，所以即使 table 按参数会落到 `tct_sg`，stock
  这条路径也不会把 table 写入 CXD3778GF tone RAM。
- 写完整 `/proc/icx_audio_cxd3778gf_data/tct` 后，9 张 table 的内核内存摘要
  都能变成 BL3 all-target table；这证明 proc 写入和内存表替换有效。
- 但 `tone_control_hw_apply=0` 不变，说明“表已进驱动内存”和“硬件 tone RAM
  已更新”是两件事。ZX300A 表不生效的主要原因在路径门控，而不是 RBJ/SGD
  生成算法或 checksum。

重启事故记录：

- 早期 `cxd3778gf_trace` kprobe 模块在 ZX300A 上加载时导致设备重启。
- `/proc/last_kmsg` 记录 `insmod` 访问 `c063b084`
  (`cxd3778gf_apply_table_change`) 时 Oops。
- 判断原因是 kprobe 注册时需要 patch 内核文本，而该符号/内核文本映射在这台
  设备上不适合这样处理。
- 后续不要默认使用 kprobe 跟踪模块；用只读状态模块做确认。

## ZX300A TYPE_Z 修正模块

在确认 stock `adjust_tone_control()` 被 TYPE_Z gate 挡住后，新增
`cxd3778gf_tone_apply` 模块：

- 源码：`tools/kernel_modules/cxd3778gf_tone_apply/cxd3778gf_tone_apply.c`。
- 编译：`experiments/reproduce/72_build_cxd3778gf_tone_apply_module.sh`。
- 安装：`experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh`。
- 手动刷 tone RAM：`experiments/reproduce/98_apply_cxd3778gf_tone_ram.sh`。
- 卸载：`experiments/reproduce/99_uninstall_cxd3778gf_tone_apply_module.sh`。

设计原则：

- `insmod` 只解析 `present`、`cxd3778gf_tone_control_table`、
  `cxd3778gf_register_modify()`、`cxd3778gf_register_write()`、
  `cxd3778gf_register_write_multiple()`，然后创建
  `/proc/cxd3778gf_tone_apply`。
- 不使用 kprobe，不修改内核文本。
- 不在加载时自动写寄存器；必须显式执行
  `echo apply > /proc/cxd3778gf_tone_apply`。
- `apply` 会按当前 `present` 状态选择 table；也可以用 `table N` 强制刷入
  0..8 的指定 table。
- MEM 写入序列直接复制 stock `adjust_tone_control()` 中的
  `CODEC_EN/CLK_HALT/MEM_CTRL/MEM_ADDR/MEM_WDAT` 顺序，只移除 TYPE_A 限制。

实机验证：

- 先刷 stock flat `tct_sg`，`last_result=0`，无重启。
- 再用 ZX300A `tc_127x.tbl` 生成 all-target 强刺激表：
  - `probe-4k-plus20`
  - `probe-4k-minus20`
  - `probe-80hz-plus20`
  - `probe-80hz-minus20`
- 写完整 `/proc/icx_audio_cxd3778gf_data/tct` 后，回读 MD5 与 table body 匹配。
- 再执行 `echo apply > /proc/cxd3778gf_tone_apply`，模块显示
  `last_result=0`。
- 用户听感确认：4 kHz 正负 20 dB、80 Hz 正负 20 dB 均有明显且方向正确的变化。

结论：

- ZX300A 的 table 生成、proc 写入和 checksum 都是有效的。
- 真正缺失的是 TYPE_Z 上的硬件 tone RAM 刷新。
- 当前可工作的非持久化方案是：写完整 `tct` 后调用 `cxd3778gf_tone_apply`
  手动刷新 tone RAM。
- 正式应用 BL3 all-target RBJ 表的复现命令：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/94_apply_bl3_zx300a_all_targets_and_tone_ram.sh
```

恢复 stock 并刷回硬件：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/93_restore_zx300a_stock_tct_and_tone_ram.sh
```

### 开机自动加载与自动应用

为了避免每次重启后手动 `insmod`，已经按 `ud505_hook` 的方式接入
`/system/bin/bootswitcher.sh`：

- 模块安装位置：`/system/lib/modules/cxd3778gf_tone_apply.ko`。
- 自动表位置：`/data/local/cxd3778gf_tone/auto_tct.tbl`。
- 启动流程：
  1. `bootswitcher.sh` 自动 `insmod cxd3778gf_tone_apply.ko`。
  2. 等待 `/proc/cxd3778gf_tone_apply` 和 `/proc/icx_audio_cxd3778gf_data/tct`。
  3. 如果 `auto_tct.tbl` 存在，写完整 `tct`。
  4. 执行 `echo table 5 > /proc/cxd3778gf_tone_apply`，强制刷入 `tct_sg`。

安装脚本：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_autoload.sh
```

设置自动应用的 table：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/98_set_cxd3778gf_tone_autoload_table.sh
```

卸载脚本：

```bash
cd /home/neoncloud/zx300-peq-research
bash experiments/reproduce/99_uninstall_cxd3778gf_tone_apply_autoload.sh
```

2026-06-28 实机重启验证：

```text
cxd3778gf_tone_apply 4984 0 - Live ...
ud505_hook 3834 1 - Live ...
md5(auto_tct.tbl) = 9839a69fba594c8320abbf9d0b6452e0
md5(/proc/.../tct body) = 4f707f6902c7e0cfec92ca182a70db14
dmesg: cxd3778gf_tone_apply: applied table=5(tct_sg/samp_general_hp)
```

## RBJ 起点加权二次优化

新增方法：在 RBJ 5 段结构不变的前提下，显式分两阶段优化。

第一阶段：

- 使用原始 RBJ 拟合权重。
- 在 `LSC/PK/HSC` 这些安全、可解释的 RBJ 滤波器参数空间内做
  `least_squares`。
- 得到一个稳定 IIR 起点，避免直接从随机或自由 SOS 进入不自然解。

第二阶段：

- 从第一阶段 IIR 参数继续优化。
- 残差仍是 dB 幅频误差，但 1 kHz 到 6 kHz 加权。
- 默认权重 `SENSITIVE_WEIGHT=2.0`；这个值比 `3.0` 更稳，全频误差代价较小。

实现：

- 工具：`tools/fit_cxd3778gf_iir_to_wav.py`
- 新参数：
  - `--refine-from-rbj`
  - `--sensitive-band 1000,6000`
  - `--sensitive-weight 2.0`
- 复现脚本：
  `experiments/reproduce/15_bl3_rbj_refine_sensitive_zx300a_all_targets.sh`
- 应用脚本：
  `experiments/reproduce/94_apply_bl3_rbj_refine_sensitive_zx300a_and_tone_ram.sh`

当前 BL3 / ZX300A all-target 结果：

```text
旧 RBJ all-target:
  full-band RMS     0.2761 dB
  1k-6k RMS         0.4073 dB
  max abs error     1.2487 dB

RBJ 起点 + 1k-6k 加权二次优化:
  full-band RMS     0.2835 dB
  1k-6k RMS         0.3887 dB
  max abs error     1.2753 dB
```

当前选中拓扑：

```text
LSC,PK,PK,PK,PK
Preamp -3.6455 dB
Filter 1: LSC 959.96 Hz +3.220 dB Q 1.000
Filter 2: PK  287.37 Hz -3.317 dB Q 0.393
Filter 3: PK  3090.58 Hz -1.863 dB Q 4.770
Filter 4: PK  10556.43 Hz +7.440 dB Q 0.776
Filter 5: PK  20000.00 Hz -17.811 dB Q 0.427
```

输出：

```text
samples/autoeq/bl3-zx300a-rbj-refine-sensitive-all-targets/full-table/tc_127x.bl3-zx300a-rbj-refine-sensitive-all-targets.tbl
samples/autoeq/bl3-zx300a-rbj-refine-sensitive-all-targets/plots/bl3-zx300a-rbj-refine-sensitive-all-targets.svg
samples/autoeq/bl3-zx300a-rbj-refine-sensitive-all-targets/plots/bl3-zx300a-rbj-refine-sensitive-all-targets.csv
```
