# ZX300A USB DAC 调音表定量验证报告

测试日期：2026-07-25

## 1. 目的与结论

本实验通过真实模拟回环，定量检查三个问题：

1. 写入 CXD3778GF tone table 后，滤波是否真的作用于耳机输出；
2. 五级串联二阶 IIR（biquad）模型能否预测实测频响；
3. 生成系数时使用的采样率是否正确。

结论如下：

- tone table 写入和强制应用路径有效，恢复原厂表也有效；
- 在 ZX300A 的 USB DAC 模式、48 kHz USB 输入下，tone IIR 的等效运行采样率是
  **192 kHz**，即输入采样率的 4 倍；
- 使用 192 kHz 生成系数后，1 kHz `+12 dB` 实测为 `+11.61 dB`，4 kHz
  `-12 dB` 实测为 `-11.59 dB`；
- 单段滤波在 30 Hz 至 18 kHz 范围内的理论/实测 RMSE 均约为 `0.51 dB`，
  相关系数约为 `0.988`；
- 两次原厂基线的 RMSE 为 `0.0228 dB`，恢复前后的 RMSE 为 `0.0175 dB`。

这组结果确认了我们当前使用的五段 biquad 参数解释和频响计算是正确的，也确认了
自定义 table 能按预期改变硬件频响。它不单独证明芯片内部绝无其他滤波单元，但已经
验证了 table 暴露出的五段能够按级联 biquad 模型工作。

![192 kHz 系数校正后的理论与实测频响](../samples/measurements/zx300a-usb-dac-4x-clock-corrected/frequency_response.png)

## 2. 测试链路

```text
Windows 48 kHz 测试信号
  -> USB
ZX300A（USB DAC 模式，CXD3778GF tone DSP）
  -> 3.5 mm 模拟输出
OsmoPocket3 录音输入
  -> USB
Windows 录音与分析
```

播放设备为 `Speakers (WALKMAN)`，录音设备为
`Capture Input terminal (OsmoPocket3)`。播放与录音均通过 Windows WDM-KS
独占模式打开，避免系统混音器、音效和其他应用插入测试链路。采集格式为 48 kHz，
激励电平为 `-32 dBFS`，所有录音均未削波。

ADB 使用 `E:\Downloads\platform-tools\adb.exe`，仅负责备份、写入、应用和恢复
tone table。音频设备访问全部在 Windows 完成，以避免 USB 设备跨 WSL 转发造成的不确定性。

## 3. 为什么没有直接使用传统扫频

最初使用单频对数扫频时，OsmoPocket3 的自动增益/动态处理会跟随扫频电平变化。
理论上的约 `12 dB` 峰谷在录音中只剩约 `1 dB`，因此单频扫频不能用于可靠的幅度定量。

最终采用确定性周期宽带噪声：

- 20 Hz 至 20 kHz 的全部频率同时存在；
- 每个 table 使用完全相同的激励；
- 丢弃前两个周期，保留 14 个稳定周期做同步平均；
- 以原厂 table 为参考计算复数频谱比；
- 去除每次录音的单一全局电平偏移，仅比较相对频响。

这样 Osmo 的慢速自动增益主要表现为全频段共同增益，归一化后不会抹平滤波器的频率形状。
原厂基线仅 `0.0228 dB` 的重复性误差也证明该方法足以分辨本实验中的变化。

## 4. 4 倍 DSP 时钟的发现

先按旧假设，为 48 kHz 生成 RBJ biquad 系数。实测中心频率如下：

| table 设定 | 理论中心（按 192 kHz 重算） | 实测中心附近幅度 | 观察 |
|---|---:|---:|---|
| 1 kHz，+12 dB，Q=1 | 4.025 kHz，+12.00 dB | +11.65 dB | 中心约为设定的 4 倍 |
| 4 kHz，-12 dB，Q=1 | 15.901 kHz，-12.00 dB | -11.52 dB | 中心约为设定的 4 倍 |
| 100 Hz，+9 dB，Q=1 | 398.7 Hz，+8.90 dB | +8.61 dB | 第三个独立的 4 倍证据 |

偏移并非随机误差：使用 192 kHz 重新解释同一组系数后，完整频响与实测高度吻合。
因此可判定，在这条 48 kHz USB DAC 通路中，tone IIR 运行在 192 kHz。

随后改用 192 kHz 生成 48 kHz 音频族系数，中心频率准确回到设定位置。44.1 kHz
音频族对应使用 176.4 kHz 是基于同一 4 倍关系的推断，本次回环没有直接测量 44.1 kHz。

旧系数的时钟校准图和数据保存在：

- `samples/measurements/zx300a-usb-dac-clock-calibration/frequency_response.png`
- `samples/measurements/zx300a-usb-dac-clock-calibration/frequency_response.csv`
- `samples/measurements/zx300a-usb-dac-clock-calibration/metrics.json`

## 5. 192 kHz 系数验证结果

| 测试 table | 关注频率理论值 | 关注频率实测值 | 30 Hz-18 kHz RMSE | 1-6 kHz RMSE | 相关系数 |
|---|---:|---:|---:|---:|---:|
| 1 kHz，+12 dB，Q=1 | +12.00 dB | +11.61 dB | 0.512 dB | 0.687 dB | 0.9880 |
| 4 kHz，-12 dB，Q=1 | -12.00 dB | -11.59 dB | 0.511 dB | 0.845 dB | 0.9883 |
| 100/+9、1k/-9、6k/+9 dB | 100 Hz: +8.90 dB | 100 Hz: +8.25 dB | 0.814 dB | 1.214 dB | 0.9882 |

三段同时启用时仍保持高度相关，说明多段级联的实现与理论一致。误差主要来自
OsmoPocket3 的不可关闭动态处理、模拟链路噪声、有限频率分辨率和 CXD3778GF
定点系数量化；当前数据没有显示滤波方向颠倒、段间顺序异常或明显的不稳定行为。

完整数据：

- `samples/measurements/zx300a-usb-dac-4x-clock-corrected/frequency_response.csv`
- `samples/measurements/zx300a-usb-dac-4x-clock-corrected/metrics.json`

## 6. 适用范围与限制

- **已验证：** ZX300A、USB DAC 模式、48 kHz USB 输入、单端 3.5 mm 输出、
  table 5 / `tct_sg` 通路。
- **尚未验证：** ZX300A 本机播放器通路、44.1 kHz 输入、平衡输出，以及其他
  A/ZX/WM 型号是否使用相同的 4 倍 tone DSP 时钟。
- OsmoPocket3 不是测量声卡，因此本报告适合验证滤波形状、中心频率和大幅度增益，
  不应被当作播放器绝对失真、噪声或高精度幅相指标。
- 主生成器已经采用本次实测支持的 176.4/192 kHz 默认值，同时保留
  `--fs441` / `--fs48` 参数。尚未测量的设备或播放通路可以显式覆盖，
  不应把默认值当作所有 CXD3778GF 设备均已验证的结论。

## 7. 完整复现命令

开始前暂停 Windows 和播放器上的所有其他音频，让 ZX300A 进入 USB DAC 模式，
确认 3.5 mm 输出已连接 OsmoPocket3 录音输入。

```powershell
cd D:\Documents\zx300-custom-kernel\walkman-tuning-guide
C:\Python312\python.exe -m pip install -r requirements.txt

# 传统对数扫频，仅用于复现 Osmo 自动增益的限制。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\40_zx300a_usb_dac_loopback_sweep.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-sweep

# 用旧 44.1/48 kHz 系数测出 4 倍中心频率偏移。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\41_zx300a_usb_dac_periodic_noise.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-clock-calibration `
  -LevelDbfs -32 -Periods 16

# 用 176.4/192 kHz 系数完成最终验证。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\42_zx300a_usb_dac_4x_clock_corrected.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-4x-clock-corrected `
  -LevelDbfs -32 -Periods 16
```

脚本只会在音频流关闭后写 table；恢复时会为 2880 字节 table body 添加 Sony
8 字节校验和，再写回 2888 字节完整 table。不要在播放/录音流活跃时手工向
`/proc/icx_audio_cxd3778gf_data/tct` 写入。

## 8. 测试结束状态

测试结束后已经写回带正确校验和的原厂 table，并重新应用 table 5。设备报告：

```text
inferred_tone_table=5(tct_sg/samp_general_hp)
inferred_table_summary=sum=0x00000140 xor=0 nonzero=10
last_result=0
```

恢复后的频响与测试前原厂基线 RMSE 为 `0.0175 dB`，可视为已经恢复到测量前状态。
