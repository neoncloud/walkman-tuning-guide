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

同一组逻辑滤波器会分别以 44100 Hz 和 48000 Hz 采样率计算一次，写入 chunk 的两个 half。

The same logical filter set is calculated twice, at 44100 Hz and 48000 Hz, and written into the two halves of the chunk.

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
