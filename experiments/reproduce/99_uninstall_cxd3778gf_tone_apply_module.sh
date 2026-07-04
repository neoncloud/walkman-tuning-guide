#!/usr/bin/env bash

# 卸载当前运行中的 CXD3778GF tone RAM 手动应用模块。
# 只执行 rmmod，不修改 /system/bin/bootswitcher.sh；autoload 请使用
# 99_uninstall_cxd3778gf_tone_apply_autoload.sh 单独移除。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

"$ADB" start-server >/dev/null
"$ADB" wait-for-device
"$ADB" shell "rmmod cxd3778gf_tone_apply 2>/dev/null || true"
"$ADB" shell "if [ -d /sys/module/cxd3778gf_tone_apply ]; then echo 'still loaded'; exit 1; else echo 'cxd3778gf_tone_apply unloaded'; fi"
