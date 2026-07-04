#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_DIR="${MODULE_DIR:-$ROOT/kernel_modules/cxd3778gf_tone_apply}"
KDIR="${KDIR:-/home/neoncloud/zx300-custom-kernel/work/kernel}"
CROSS_COMPILE="${CROSS_COMPILE:-/tmp/zx300-linaro-good/gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf/bin/arm-linux-gnueabihf-}"

[[ -d "$MODULE_DIR" ]] || { echo "missing module dir: $MODULE_DIR" >&2; exit 2; }
[[ -d "$KDIR" ]] || { echo "missing kernel tree: $KDIR" >&2; echo "set KDIR=/path/to/prepared/kernel" >&2; exit 2; }
[[ -x "${CROSS_COMPILE}gcc" ]] || { echo "missing cross compiler: ${CROSS_COMPILE}gcc" >&2; echo "set CROSS_COMPILE=/path/to/arm-linux-gnueabihf-" >&2; exit 2; }

cd "$MODULE_DIR"
make clean KDIR="$KDIR" CROSS_COMPILE="$CROSS_COMPILE"
make strip KDIR="$KDIR" CROSS_COMPILE="$CROSS_COMPILE"
modinfo cxd3778gf_tone_apply.ko
