# ZX300A USB DAC 回环扫频测试报告

- 电脑侧采样率：48000 Hz；tone IIR 实际运行采样率：192000 Hz。

## 测试指标

| 配置 | 30 Hz-18 kHz RMSE | 1-6 kHz RMSE | 相关系数 | 关键频点理论 | 关键频点实测 |
|---|---:|---:|---:|---:|---:|
| etymotic_evo_2flange | 0.32 dB | 0.41 dB | 0.9955 | 1732 Hz / -13.00 dB | 1732 Hz / -12.79 dB |

- 两次基线的形状重复性 RMSE：0.018 dB。
- 恢复基线后相对恢复前的 RMSE：0.018 dB。
- 对每个自定义配置仅移除了一个全频段常量电平偏差；曲线形状没有做拟合或缩放。
- 详细数据见 `frequency_response.csv`，自动对齐诊断见 `metrics.json`。

![频响对比](frequency_response.png)
