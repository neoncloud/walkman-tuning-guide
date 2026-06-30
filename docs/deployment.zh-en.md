# 部署指南 / Deployment Guide

## A-series / A 系列

A50 validation showed that `/proc/icx_audio_cxd3778gf_data/tct_*` writes can update the corresponding 320-byte chunk, and readback can verify the write.

Recommended flow:

```bash
mkdir -p backups out
tools/autoeq_to_cxd3778gf_peq.py my-autoeq.txt out/my.peq.tbl --filter-strategy best
tools/apply_cxd3778gf_peq_adb.sh --input my-autoeq.txt --target sg --filter-strategy best
```

Restore:

```bash
tools/apply_cxd3778gf_peq_adb.sh --restore --target sg
```

## ZX300A / ZX 系列

ZX300A stock driver updates the in-memory table but does not reload CXD3778GF tone RAM on the normal `TYPE_Z` path. Use the helper module:

```bash
bash scripts/build_zx300_tone_apply.sh
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh
```

After writing a full `tc_*.tbl` to `/proc/icx_audio_cxd3778gf_data/tct`, trigger:

```bash
bash experiments/reproduce/98_apply_cxd3778gf_tone_ram.sh
```

Autoload is optional and riskier because it edits `/system/bin/bootswitcher.sh`:

```bash
bash experiments/reproduce/97_install_cxd3778gf_tone_apply_autoload.sh
bash experiments/reproduce/98_set_cxd3778gf_tone_autoload_table.sh
```

Remove autoload:

```bash
bash experiments/reproduce/99_uninstall_cxd3778gf_tone_apply_autoload.sh
```

## Targets / 目标 chunk

Known chunk names:

- `nh`: no headphone
- `ng`: normal amp, general headphone
- `nnw500`, `nnw750`, `nnc31`: normal amp, Sony NC headphone cases
- `sg`: S-Master amp, general headphone
- `snw500`, `snw750`, `snc31`: S-Master amp, Sony NC headphone cases

For most experiments, use `sg` or generate an all-target table.
