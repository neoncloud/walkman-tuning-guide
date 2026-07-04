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
