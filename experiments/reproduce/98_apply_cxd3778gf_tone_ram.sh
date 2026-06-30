#!/usr/bin/env bash

# 手动把当前驱动内存中的 tone table 刷入 CXD3778GF tone RAM。
# 默认按当前 output/headphone_amp/headphone_type/jack_status 自动选择 table。
# 可通过 TABLE=5 强制选择指定 table。

set -euo pipefail

ADB="${ADB:-/mnt/e/Downloads/platform-tools/adb.exe}"
TABLE="${TABLE:-auto}"

"$ADB" start-server >/dev/null
"$ADB" wait-for-device

if [[ "$TABLE" == "auto" ]]; then
  "$ADB" shell "echo apply > /proc/cxd3778gf_tone_apply"
else
  "$ADB" shell "echo table '$TABLE' > /proc/cxd3778gf_tone_apply"
fi

"$ADB" shell "cat /proc/cxd3778gf_tone_apply"
"$ADB" shell "dmesg | grep 'cxd3778gf_tone_apply' | tail -30"
