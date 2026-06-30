#!/usr/bin/env bash

# 恢复 ZX300A stock tct，并通过 cxd3778gf_tone_apply kmod 手动刷入 tone RAM。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

bash "$SCRIPT_DIR/93_restore_zx300a_stock_tct.sh"
"$ADB" shell "echo apply > /proc/cxd3778gf_tone_apply"
"$ADB" shell "cat /proc/cxd3778gf_tone_apply"
"$ADB" shell "dmesg | grep 'cxd3778gf_tone_apply' | tail -30"
