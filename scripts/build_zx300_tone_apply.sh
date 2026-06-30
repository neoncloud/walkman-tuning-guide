#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_DIR="${MODULE_DIR:-$ROOT/kernel_modules/cxd3778gf_tone_apply}"
KDIR="${KDIR:-/tmp/zx300-lkm-fresh-20260623/kernel}"
CROSS_COMPILE="${CROSS_COMPILE:-/tmp/zx300-linaro-good/gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf/bin/arm-linux-gnueabihf-}"

cd "$MODULE_DIR"
make clean KDIR="$KDIR" CROSS_COMPILE="$CROSS_COMPILE"
make strip KDIR="$KDIR" CROSS_COMPILE="$CROSS_COMPILE"
modinfo cxd3778gf_tone_apply.ko
