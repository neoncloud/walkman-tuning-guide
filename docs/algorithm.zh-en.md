# 算法原理 / Algorithm

## 调音表模型 / Tone Table Model

CXD3778GF tone table 当前按以下结构解释：

The CXD3778GF tone table is currently interpreted as:

- 完整 `tc_*.tbl`：2880-byte body + 8-byte Sony checksum。  
  Full `tc_*.tbl`: 2880-byte body plus 8-byte Sony checksum.
- 9 个 chunk，每个 320 bytes。  
  9 chunks, 320 bytes each.
- 每个 chunk 有两个 160-byte half。  
  Each chunk has two 160-byte halves.
- 每个 half 有 32 个 signed 40-bit big-endian Q37 word。  
  Each half has 32 signed 40-bit big-endian Q37 words.
- 每个 half 前 25 个 word 是 5 个 biquad：`b0, b1, b2, -a1, -a2`。  
  The first 25 words of each half are five biquads: `b0, b1, b2, -a1, -a2`.
- 剩余 7 个 word 当前视为保留/填充。  
  The remaining 7 words are currently treated as reserved/padding.

`0x20 00 00 00 00` 解码为 Q37 的 `1.0`。原厂 general headphone 表里大量 identity section 与这个解释一致。

`0x20 00 00 00 00` decodes to Q37 `1.0`. The many identity sections in stock general-headphone tables match this interpretation.

仓库不会分发 Sony 原厂 tone table。需要 base table 时，工具可以生成全 identity 的空白表：

This repository does not redistribute Sony stock tone tables. When a base table is needed, the tool can generate a blank all-identity table:

```bash
python3 tools/cxd3778gf_tct_tool.py make-identity backups/tc_127x.tbl
```

## RBJ 是什么 / What RBJ Means

RBJ 指 Robert Bristow-Johnson。他整理的 **Audio EQ Cookbook** 是音频 DSP 中非常常用的一组 biquad 公式，可以把 peak、low shelf、high shelf 等 EQ 参数转换为标准二阶 IIR 滤波器系数。

RBJ refers to Robert Bristow-Johnson. His **Audio EQ Cookbook** is a widely used set of biquad formulas in audio DSP. It converts peak, low-shelf, high-shelf, and related EQ parameters into standard second-order IIR coefficients.

本项目使用 RBJ 公式的原因：

Why this project uses RBJ formulas:

- 和 AutoEq 输出的 PEQ 参数天然匹配。  
  They naturally match AutoEq PEQ parameters.
- 数学形式稳定、可解释、容易检查。  
  The form is stable, explainable, and easy to inspect.
- 生成结果在硬件上比无约束优化更安全。  
  The generated filters are safer on hardware than unconstrained optimization.
- 实测中，RBJ 五段基线是当前最准确、最可靠的方案。  
  In experiments, the five-section RBJ baseline has been the most accurate and reliable method so far.

## PEQ 到 Biquad / PEQ to Biquad

AutoEq 文本通常类似：

AutoEq text usually looks like:

```text
Preamp: -4.0 dB
Filter 1: ON LS Fc 105 Hz Gain 3.0 dB Q 0.70
Filter 2: ON PK Fc 950 Hz Gain -2.5 dB Q 1.10
Filter 3: ON HS Fc 9000 Hz Gain -1.5 dB Q 0.70
```

支持的 filter 类型：

Supported filter types:

- `PK`: peaking EQ
- `LS`: low shelf
- `HS`: high shelf

每段滤波器转换为：

Each filter is converted to:

```text
H(z) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)
```

归一化后写入 codec 的顺序是：

After normalization, the codec order is:

```text
b0, b1, b2, -a1, -a2
```

同一组逻辑滤波器会写入 chunk 的两个 half。内核源码把地址 `0x00` 和 `0x20`
分别命名为 `CODEC_RAM_441_AREA` 与 `CODEC_RAM_480_AREA`；Sony 原厂特殊耳机表
的两半也分别按 176.4/192 kHz 解释时得到几乎相同的频响。因此生成器仍按
44.1/48 kHz 音频族生成两套系数，但必须区分**音频输入采样率**、
**tone IIR 的实际运行时钟**和**当前硬件实际读取的 RAM area**。

The same logical filter set is written into both halves of the chunk. The
kernel source names addresses `0x00` and `0x20` as `CODEC_RAM_441_AREA` and
`CODEC_RAM_480_AREA`. The two halves of Sony's special-headphone tables also
produce almost identical responses when interpreted at 176.4 and 192 kHz.
The generator therefore still emits coefficient sets for the 44.1/48 kHz
families, but the **input rate**, **actual tone-IIR clock**, and **RAM area
actually read by the current path** must be kept separate.

ZX300A USB DAC 的定量回环结果为：

Quantitative ZX300A USB DAC loopback results show:

| half | 音频族 / Audio family | 默认 tone-DSP 系数时钟 / Default coefficient clock |
|---|---:|---:|
| 0 | 44.1 kHz | 176.4 kHz |
| 1 | 48 kHz | 192 kHz |

旧算法直接按 44.1/48 kHz 计算 RBJ 系数。在 48 kHz USB 输入下，设定为
1 kHz 的峰值实测出现在约 4.025 kHz，设定为 4 kHz 的陷波出现在约
15.9 kHz；使用 192 kHz 重新计算后，中心分别回到 1 kHz 和 4 kHz。
随后对八档 USB PCM 输入完成了物理回环：

The legacy algorithm calculated RBJ coefficients directly at 44.1/48 kHz.
With 48 kHz USB input, a requested 1 kHz peak appeared at about 4.025 kHz,
and a requested 4 kHz notch appeared at about 15.9 kHz. Recalculating at
192 kHz moved the centers back to 1 kHz and 4 kHz. Physical loopback was
then repeated across all eight USB PCM rates:

| USB 输入家族 / Input family | 输入档位 / Input rates | 实测 tone-DSP 时钟 / Measured tone-DSP clock |
|---|---|---:|
| 44.1 kHz | 44.1 / 88.2 / 176.4 / 352.8 kHz | 约 176.4 kHz |
| 48 kHz | 48 / 96 / 192 / 384 kHz | 约 192 kHz |

因此正确模型是“每个音频族使用固定 tone 时钟”，而不是“永远等于输入采样率
的四倍”。相对输入的倍率依次约为 4×、2×、1×、0.5×。生成器默认值写成：

The correct model is therefore a fixed tone clock per audio family, not
"always four times the input rate." Relative to the input, the ratios are
approximately 4x, 2x, 1x, and 0.5x. The generator defaults are:

```text
tone_fs_44k1_family = 176400 Hz
tone_fs_48k_family  = 192000 Hz
```

`--fs441` 和 `--fs48` 仍可覆盖默认值，用于其他型号或尚未测量的播放通路。
八档测试还发现，当前 ZX300A `TYPE_Z` 强制加载通路的左声道始终匹配 half 0，
包括 48 kHz 家族；这与源码的 family area 命名不一致。若只针对当前 USB DAC
48 kHz 通路做实验，可显式使用 `--fs441 192000 --fs48 192000`，让两半都按
192 kHz 生成；这张表不应再用于要求 44.1 kHz 精确中心频率的通路。

`--fs441` and `--fs48` can still override the defaults for other models or
unmeasured playback paths. The eight-rate test also found that the captured
left output on the current ZX300A `TYPE_Z` forced-apply path always matched
half 0, including the 48 kHz family. This conflicts with the source's family
area names. For a USB-DAC-only 48 kHz experiment, explicitly using
`--fs441 192000 --fs48 192000` makes both halves correct for that path, but
the resulting table must not be treated as exact for 44.1 kHz playback.

完整报告见
[`zx300a-usb-dac-loopback-validation.zh.md`](zx300a-usb-dac-loopback-validation.zh.md)。

## Q37 定点编码 / Q37 Fixed-Point Encoding

每个浮点系数乘以 `2^37`，四舍五入后写成 signed 40-bit big-endian：

Each floating-point coefficient is multiplied by `2^37`, rounded, and written as signed 40-bit big-endian:

```text
encoded = round(coef * 2^37)
```

写入前必须检查：

Before writing, check:

- 是否超出 signed 40-bit 范围。  
  Signed 40-bit range.
- pole radius 是否小于 1，保证 IIR 稳定。  
  Pole radius below 1 for IIR stability.
- 单段峰值和级联前缀峰值是否过大。  
  Section peak and cascade-prefix peak.
- 定点量化后频响是否仍然接近目标。  
  Whether the quantized response still matches the target.

### Preamp 与 Q37 范围 / Preamp and Q37 Range

signed 40-bit Q37 可表示的范围约为 `[-4, 4)`。在 176.4/192 kHz 时钟下，
高增益 shelf 的某个 numerator 系数可能超过这个范围，即使滤波器本身稳定。
直接截断系数会破坏频响，因此生成器采用级联等价变换：

The signed 40-bit Q37 range is approximately `[-4, 4)`. At the
176.4/192 kHz clocks, a high-gain shelf can produce a numerator coefficient
outside this range even though the filter itself is stable. Clipping the
coefficient would corrupt the response, so the generator uses an equivalent
cascade transformation:

```text
H_total = (s1 * H1) * (s2 * H2) * ... * (s5 * H5)
where s1 * s2 * ... * s5 = preamp_linear
```

默认情况下，preamp 仍全部折入第一段 numerator。只有出现 Q37 溢出时，才在
五段 numerator 之间受限分配缩放；缩放乘积严格保持原 preamp，因此总频响和
极点完全不变。若即使最优分配也无法编码，工具会拒绝输出并提示至少需要增加
多少 dB 衰减。

By default, preamp is still folded into the first numerator. Only when this
would overflow Q37 is the gain distributed across the five numerators under
per-section limits. Their product remains exactly equal to the requested
preamp, so the total response and poles do not change. If no valid
distribution exists, the tool refuses to write output and reports the
additional attenuation required.

此外，AutoEq 文件的 preamp 通常是按 44.1/48 kHz 软件 EQ 响应计算的。改用
176.4/192 kHz tone-DSP 时钟后，Nyquist 附近的双线性扭曲发生变化，原 preamp
可能不再覆盖多个滤波器的叠加峰值。AutoEq 转换器会在 20 Hz 至 20 kHz 上重新
计算两个 half 的最大增益，并在必要时增加全局衰减。可用 `--headroom-db`
预留额外余量，或用 `--preserve-preamp` 禁用自动修正。

AutoEq preamp values are normally calculated from a software EQ response at
44.1/48 kHz. At the 176.4/192 kHz tone-DSP clocks, bilinear warping near
Nyquist changes, so the original preamp may no longer cover the combined
filter peak. The AutoEq converters recalculate the maximum response of both
halves from 20 Hz to 20 kHz and add global attenuation when necessary.
`--headroom-db` reserves additional margin, while `--preserve-preamp`
disables this automatic correction.

## 超过五段 AutoEq 的处理 / More Than Five AutoEq Filters

CXD3778GF tone RAM 当前只验证出五个有效 biquad，因此 AutoEq 超过五段时必须降维。

Only five effective biquads have been validated in CXD3778GF tone RAM, so AutoEq profiles with more than five filters must be reduced.

本项目提供以下策略：

This project provides:

- `first`: 保留输入顺序前五段。  
  Keep the first five filters.
- `largest`: 保留绝对增益最大的五段。  
  Keep the five largest absolute gains.
- `wide`: 优先保留 shelf 和低 Q 宽滤波器。  
  Prefer shelves and broad low-Q filters.
- `greedy`: 每次加入最能降低 RMS 误差的一段。  
  Add the filter that most reduces RMS error at each step.
- `best`: 枚举可行组合，选择 RMS 误差最低的一组。  
  Enumerate feasible combinations and choose the lowest-RMS set.

## 从 WAV 目标拟合 / Fitting a WAV Target

对于 AutoEq minimum-phase impulse response WAV，可以直接从冲击响应得到目标频响：

For an AutoEq minimum-phase impulse response WAV, the target response can be derived directly:

1. 读取 WAV impulse response。  
   Read the WAV impulse response.
2. FFT 得到复频响。  
   Use FFT to get the complex frequency response.
3. 在 log-frequency 网格上采样 dB magnitude。  
   Sample dB magnitude on a log-frequency grid.
4. 用五个 biquad 拟合目标。  
   Fit the target with five biquads.
5. 绘制目标、IIR 响应和 error。  
   Plot target, IIR response, and error.

当前推荐策略是：

Current recommended strategy:

- 先用 RBJ / AutoEq PEQ 得到安全初值。  
  Start from safe RBJ / AutoEq PEQ filters.
- 再在目标频响上小范围优化。  
  Refine against the target response.
- 对 1 kHz 到 6 kHz 人耳敏感区加权。  
  Apply extra weight to the 1 kHz to 6 kHz sensitive band.
- 保留 pole radius、section peak、prefix peak 和 Q37 范围约束。  
  Keep pole-radius, section-peak, prefix-peak, and Q37-range constraints.

示例：

Example:

```bash
bash experiments/reproduce/15_bl3_rbj_refine_sensitive_zx300a_all_targets.sh
```

## 为什么不直接用高阶 FIR / Why Not Direct High-Order FIR

AutoEq 的 WAV correction impulse response 本质上更适合卷积滤波器，但 CXD3778GF tone table 当前暴露的是五级 IIR 参数，而不是任意长度 FIR tap。高阶 FIR、Yule-Walker、cepstrum spectral factorization、`invresz` 等方法可以作为拟合思路，但最终仍必须落到五个稳定 biquad，容量很小。

AutoEq WAV correction impulse responses are naturally suited for convolution, but the currently exposed CXD3778GF tone table stores five IIR sections, not arbitrary-length FIR taps. High-order FIR, Yule-Walker, cepstrum spectral factorization, and `invresz` are useful fitting ideas, but the final hardware target still has to be five stable biquads, which is a very small capacity.

因此，当前最可靠的路线不是追求数学上最自由的滤波器，而是在硬件容量内找到稳定、可解释、听感方向正确的五段 IIR。

Therefore, the most reliable route is not the most flexible mathematical filter, but a stable, explainable, hardware-safe five-section IIR that moves the response in the intended direction.
