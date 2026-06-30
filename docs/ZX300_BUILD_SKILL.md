# ZX300 Tone Apply Build Skill

Use this skill when an AI agent or maintainer needs to adapt the `cxd3778gf_tone_apply` helper module to another ZX/WM Walkman firmware.

## Goal

Build an out-of-tree kernel module that:

- resolves the stock `cxd3778gf` symbols with `kallsyms_lookup_name`;
- exposes `/proc/cxd3778gf_tone_apply`;
- writes one selected 320-byte tone table to CXD3778GF MEM registers;
- does not patch kernel text and does not write registers during `insmod`.

## Required inputs

- Sony GPL kernel source matching the device firmware.
- Prepared kernel tree with `.config`, `prepare`, and `scripts` completed.
- ARM hard-float cross compiler matching or close to the stock build.
- Stock `vmlinux`/`System.map` if available.
- Device readback from `/proc/icx_audio_cxd3778gf_data/tct`.

## Adaptation points

Check these before building for a non-ZX300A target:

- `struct cxd3778gf_status` layout from `<sound/cxd3778gf.h>`.
- `TYPE_A` and `TYPE_Z` constants.
- `CXD3778GF_*` register addresses.
- `CODEC_RAM_WORD_SIZE`, `CODEC_RAM_SIZE`, and table count.
- Symbol availability for:
  - `present`
  - `cxd3778gf_tone_control_table`
  - `cxd3778gf_register_write`
  - `cxd3778gf_register_modify`
  - `cxd3778gf_register_write_multiple`

## Build

```bash
KDIR=/path/to/prepared/kernel \
CROSS_COMPILE=/path/to/arm-linux-gnueabihf- \
bash scripts/build_zx300_tone_apply.sh
```

## Install

```bash
ADB=/path/to/adb bash experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh
```

## Validate

```bash
ADB=/path/to/adb adb shell cat /proc/cxd3778gf_tone_apply
ADB=/path/to/adb bash experiments/reproduce/98_apply_cxd3778gf_tone_ram.sh
```

Expected behavior:

- `insmod` only creates the proc node.
- `cat /proc/cxd3778gf_tone_apply` reports `ready=1`.
- writing `apply` or `table 5` logs `applied table=...`.

## Safety rules

- Do not load the old kprobe trace module on production devices.
- Do not patch kernel text for this flow.
- Do not add automatic register writes to module init.
- Always provide a restore script before enabling autoload.
