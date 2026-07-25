# ZX300A USB DAC 全采样率回环：DSEE 关闭

本目录归档关闭 DSEE 和其他音效后的修正版实验：

- `full/`：八档完整矩阵，每段 8 个周期；
- `outlier-repeat/`：48 与 352.8 kHz 的 16 周期定向复测；
- `comparison/`：DSEE 开启/关闭两轮的指标对比。

最终结果对 48 与 352.8 kHz 采用定向复测值。八档相对固定 family 时钟的最大
绝对误差为 `0.064%`，共同探针最大拟合 RMSE 为 `0.037 dB`，全部 tone table
均生效，当前左输出采集通路全部匹配 half 0。

完整设备回环：

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\45_measure_zx300a_all_sample_rates.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-all-sample-rates-dsee-off
```

定向复测：

```powershell
powershell -NoProfile -Command "& {
  .\experiments\reproduce\45_measure_zx300a_all_sample_rates.ps1 `
    -OutputDir experiments\measurements\zx300a-usb-dac-dsee-off-outlier-repeat `
    -Periods 16 -Rates @(48000,352800) -SkipChannelMap
}"
```

只重建 DSEE 对比报告：

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\46_compare_zx300a_dsee_sample_rate_runs.ps1
```

每次设备实验结束时都会重新应用
`/data/local/cxd3778gf_tone/auto_tct.tbl`。原始 WAV 不进入 Git。
