# ZX300A USB DAC 回环扫频测试报告

- 电脑侧采样率：48000 Hz；tone IIR 实际运行采样率：192000 Hz。

## 测试指标

| 配置 | 30 Hz-18 kHz RMSE | 1-6 kHz RMSE | 相关系数 | 关键频点理论 | 关键频点实测 |
|---|---:|---:|---:|---:|---:|
| corrected_pk_1000_plus12_q1 | 0.51 dB | 0.69 dB | 0.9880 | 1005 Hz / +12.00 dB | 1005 Hz / +11.61 dB |
| corrected_pk_4000_minus12_q1 | 0.51 dB | 0.85 dB | 0.9883 | 4025 Hz / -12.00 dB | 4025 Hz / -11.59 dB |
| corrected_three_band_100p9_1000m9_6000p9 | 0.81 dB | 1.21 dB | 0.9882 | 100 Hz / +8.90 dB | 100 Hz / +8.25 dB |

- 两次原厂基线的形状重复性 RMSE：0.023 dB。
- 恢复原厂后相对恢复前的 RMSE：0.017 dB。
- 对每个自定义配置仅移除了一个全频段常量电平偏差；曲线形状没有做拟合或缩放。
- 详细数据见 `frequency_response.csv`，自动对齐诊断见 `metrics.json`。

![频响对比](frequency_response.png)
