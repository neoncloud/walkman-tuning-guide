# ZX300A USB DAC 全采样率回环数据

本目录归档第一轮八档 USB PCM 输入的分析结果。测试后确认这一轮开启了 DSEE，
因此仅保留作对照，不再作为最终权威数据。DSEE 关闭后的修正版见
`../zx300a-usb-dac-all-sample-rates-dsee-off/`。

原始 WAV 体积较大，不进入 Git；
可在 Windows 仓库根目录完整重建：

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\45_measure_zx300a_all_sample_rates.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-all-sample-rates
```

文件说明：

- `REPORT.md`：自动生成的结论与指标表；
- `metrics.json`：每档时钟拟合、half 匹配、声道映射和对齐诊断；
- `frequency_response.csv`：全部实测与理论曲线；
- `sample_rate_matrix.png`：八档共同探针和不对称 half 探针图。

测试结束时脚本会重新应用设备上的
`/data/local/cxd3778gf_tone/auto_tct.tbl`，避免把探针表留在运行时。
