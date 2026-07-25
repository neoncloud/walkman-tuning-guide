# 复现实验脚本 / Reproduction Scripts

本目录保存项目开发过程中用过的关键实验。每个脚本都应该可以从仓库根目录直接运行。

This directory stores the key experiments used during development. Each script should be runnable from the repository root.

## 常用环境 / Common Environment

```bash
cd /home/neoncloud/walkman-tuning-guide
export ADB=/mnt/e/Downloads/platform-tools/adb.exe
python3 -m pip install -r requirements.txt
```

## 频响拟合 / Response Fitting

```bash
bash experiments/reproduce/10_blessing3_rbj_wav_fit.sh
bash experiments/reproduce/15_bl3_rbj_refine_sensitive_zx300a_all_targets.sh
bash experiments/reproduce/20_blessing3_torch_sgd_5sos.sh
```

- `10`: RBJ 五段基线。  
  RBJ five-section baseline.
- `15`: RBJ 初值 + 1 kHz 到 6 kHz 加权优化，当前推荐。  
  RBJ initialization plus 1 kHz to 6 kHz weighted refinement; currently recommended.
  如果缺少 `backups/tc_127x.tbl`，脚本会自动生成 identity base，不会要求仓库携带 Sony 原厂表。  
  If `backups/tc_127x.tbl` is missing, the script creates an identity base and does not require Sony stock tables in the repository.
- `20`: Torch SOS 直接优化实验，噪声风险更高，仅作研究。  
  Torch SOS direct optimization experiment; higher noise risk, research only.

## ZX300A Kernel Module / ZX300A 内核模块

```bash
bash experiments/reproduce/72_build_cxd3778gf_tone_apply_module.sh
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh
bash experiments/reproduce/98_apply_cxd3778gf_tone_ram.sh
```

## 应用与还原 / Apply and Restore

```bash
bash experiments/reproduce/94_apply_bl3_rbj_refine_sensitive_zx300a_and_tone_ram.sh
bash experiments/reproduce/93_restore_zx300a_stock_tct_and_tone_ram.sh
```

## 开机自动加载 / Autoload

```bash
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_autoload.sh
bash experiments/reproduce/98_set_cxd3778gf_tone_autoload_table.sh path/to/full-table.tbl
bash experiments/reproduce/99_uninstall_cxd3778gf_tone_apply_autoload.sh
```

autoload 会修改 `/system/bin/bootswitcher.sh`。启用前请先确认手动 apply 已经工作。

Autoload edits `/system/bin/bootswitcher.sh`. Confirm manual apply works before enabling it.

## Windows 回环测量 / Windows Loopback Measurement

以下实验在 Windows 中直接访问 WALKMAN、OsmoPocket3 和 ADB。开始前请暂停所有其他播放，
并让 ZX300A 进入 USB DAC 模式。WDM-KS 使用独占模式，测量期间不要让其他程序占用设备。

The following experiments access the WALKMAN, OsmoPocket3, and ADB directly from
Windows. Pause all other playback and put the ZX300A in USB DAC mode first.
WDM-KS is exclusive, so no other application may use either audio device.

```powershell
cd D:\Documents\zx300-custom-kernel\walkman-tuning-guide
C:\Python312\python.exe -m pip install -r requirements.txt

# 单音对数扫频：用于展示 Osmo AGC 对传统扫频的影响。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\40_zx300a_usb_dac_loopback_sweep.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-sweep

# 旧 44.1/48 kHz 系数：用于测量中心频率偏移并校准 DSP 时钟。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\41_zx300a_usb_dac_periodic_noise.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-clock-calibration `
  -LevelDbfs -32 -Periods 16

# 48 kHz 基础档：验证 192 kHz tone 时钟和五段级联。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\42_zx300a_usb_dac_4x_clock_corrected.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-4x-clock-corrected `
  -LevelDbfs -32 -Periods 16

# 八档输入：验证固定 176.4/192 kHz family 时钟、活动 half 和左右声道映射。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\45_measure_zx300a_all_sample_rates.ps1 `
  -OutputDir experiments\measurements\zx300a-usb-dac-all-sample-rates
```

脚本默认使用 `E:\Downloads\platform-tools\adb.exe`。`40` 至 `42` 会备份并恢复
测量前的 table；`45` 在 `finally` 中重新应用设备上的持久化 `auto_tct.tbl`。
完整结论见
[`docs/zx300a-usb-dac-loopback-validation.zh.md`](../../docs/zx300a-usb-dac-loopback-validation.zh.md)。

### Etymotic EVO 2-flange：生成并持久化安装

脚本会先备份当前 proc table 和现有 `auto_tct.tbl`，明确使用
`176400/192000 Hz` 生成完整 table，校验本地/远端 MD5，随后写入运行时并设为
开机自动加载的 table。写表前必须停止所有播放和录音。

```powershell
cd D:\Documents\zx300-custom-kernel\walkman-tuning-guide
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\43_install_etymotic_evo_2flange_zx300a.ps1 `
  -Input "E:\Downloads\Etymotic Evo (2-flange eartips) ParametricEq.txt"

# 安装后进行原厂/EVO 周期宽带回环，并在结束时重新应用 EVO。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\44_measure_etymotic_evo_2flange_loopback.ps1

# 枚举 44.1 kHz 至 384 kHz 全部 USB DAC PCM 档位，反推固定 DSP Fs、
# 当前采集通路读取的 half，并确认单声道录音线接到左输出。
powershell -ExecutionPolicy Bypass -File `
  .\experiments\reproduce\45_measure_zx300a_all_sample_rates.ps1
```
