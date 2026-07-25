# ZX300A USB DAC 全采样率 tone-DSP 回环报告

> 本轮已关闭 DSEE 和其他音效。48/352.8 kHz 的首轮异常点随后用 16 周期复测；
> 合并后的最终指标见 `../comparison/REPORT.md`。

## 结论

- 44.1 kHz 家族在全部四档输入下均符合约 176.4 kHz 的固定 tone-DSP 时钟。
- 48 kHz 家族在全部四档输入下均符合约 192 kHz 的固定 tone-DSP 时钟。
- 因而相对 USB 输入的倍率依次为约 4×、2×、1×、0.5×；“4×”只适用于 44.1/48 kHz 基础档。
- 352.8/384 kHz 输入下 tone table 仍然生效，没有在 192 kHz 以上旁路。

| USB 输入 | tone 生效 | 拟合 DSP Fs | 相对输入倍率 | 相对 family 固定时钟误差 | 共同探针 RMSE | 采集通路匹配 | half RMSE |
|---:|:---:|---:|---:|---:|---:|:---:|---:|
| 44100 Hz | 是 | 176302 Hz | 3.9978x | -0.056% | 0.028 dB | half 0 | 0.026 dB |
| 48000 Hz | 是 | 189918 Hz | 3.9566x | -1.084% | 0.197 dB | half 0 | 0.035 dB |
| 88200 Hz | 是 | 176373 Hz | 1.9997x | -0.015% | 0.025 dB | half 0 | 0.026 dB |
| 96000 Hz | 是 | 191965 Hz | 1.9996x | -0.018% | 0.037 dB | half 0 | 0.042 dB |
| 176400 Hz | 是 | 176415 Hz | 1.0001x | +0.009% | 0.027 dB | half 0 | 0.024 dB |
| 192000 Hz | 是 | 192027 Hz | 1.0001x | +0.014% | 0.036 dB | half 0 | 0.036 dB |
| 352800 Hz | 是 | 178026 Hz | 0.5046x | +0.922% | 0.174 dB | half 0 | 0.192 dB |
| 384000 Hz | 是 | 192122 Hz | 0.5003x | +0.064% | 0.031 dB | half 0 | 0.036 dB |

- 共同探针在两个 half 中写入完全相同的 1 kHz/+12 dB 系数，系数参考时钟为 48 kHz。
- WALKMAN 由 Windows WDM-KS 分别以八档采样率独占播放；OsmoPocket3 固定以 48 kHz 采集，分析时对激励做 polyphase 重采样。
- 拟合只移除一个全频段常量电平偏差，没有缩放曲线。
- half 探针为 half 0 的 700 Hz/+12 dB 与 half 1 的 3 kHz/-12 dB。
- 八档结果都表示当前模拟采集通路与 half 0（源码名 `CODEC_RAM_441_AREA`）的探针曲线一致；它与源码暗示的自动 family area 切换并不一致。
- 详细曲线见 `frequency_response.csv`，自动对齐信息见 `metrics.json`。
- 48 kHz 左右声道映射中，左声道单独播放比右声道单独播放高 34.93 dB；当前线缆实际采集 WALKMAN 左声道输出。
- 因此本次无法对未接入的另一个模拟声道及其 half 行为作物理回环结论。

![全采样率矩阵](sample_rate_matrix.png)

完整复现脚本：`experiments/reproduce/45_measure_zx300a_all_sample_rates.ps1`。
