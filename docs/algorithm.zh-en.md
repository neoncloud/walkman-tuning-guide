# 算法原理 / Algorithm

## Table model / 调音表模型

`tc_*.tbl` tone table is treated as:

- 2880-byte body plus 8-byte Sony checksum.
- 9 chunks, 320 bytes each.
- 2 halves per chunk, 160 bytes each.
- 32 signed 40-bit big-endian Q37 words per half.
- First 25 words are five biquads: `b0, b1, b2, -a1, -a2`.
- Last 7 words are currently reserved/padding.

`0x20 00 00 00 00` decodes to `1.0`, which makes the stock general headphone table decode as five identity sections.

## PEQ conversion / PEQ 转换

For AutoEq text profiles, the tool parses lines like:

```text
Preamp: -4.0 dB
Filter 1: ON LS Fc 105 Hz Gain 3.0 dB Q 0.70
Filter 2: ON PK Fc 950 Hz Gain -2.5 dB Q 1.10
Filter 3: ON HS Fc 9000 Hz Gain -1.5 dB Q 0.70
```

Supported types are `PK`, `LS`, and `HS`. Each filter is converted using RBJ audio EQ cookbook formulas, normalized by `a0`, then written in the codec order `b0, b1, b2, -a1, -a2`.

The same logical filter set is encoded twice: once at `44100 Hz`, once at `48000 Hz`. This matches the current interpretation of the two 160-byte halves.

## Overflow and safety / 溢出与安全

Every coefficient is checked against signed 40-bit Q37 range. A filter set may be mathematically valid but still unsafe on hardware if intermediate sections produce large peaks that cancel later. The fitting scripts therefore track:

- total response error;
- section peak;
- prefix peak;
- pole radius;
- coefficient range.

## More than five filters / 超过五段滤波器

CXD3778GF tone RAM has room for five effective biquad sections. When AutoEq gives more filters, choose a reduction strategy:

- `first`: preserve the first five enabled filters.
- `largest`: keep filters with the largest absolute gains.
- `wide`: prefer shelves and broad low-Q filters.
- `greedy`: add the section that most reduces RMS dB error.
- `best`: enumerate combinations and choose the lowest RMS error where feasible.

## WAV target fitting / WAV 目标拟合

For minimum-phase WAV targets, `fit_cxd3778gf_iir_to_wav.py` and `fit_cxd3778gf_torch_sos_to_wav.py` read the impulse response, FFT it, use log-frequency dB samples as the target, then optimize five sections.

RBJ fitting is safer and explainable. Torch SOS fitting is more powerful, but must be constrained to avoid noisy hardware behavior.
