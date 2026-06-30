#!/usr/bin/env bash

# 推送并安装 CXD3778GF tone RAM 手动应用模块。
# 安装只创建 /proc/cxd3778gf_tone_apply，不会自动写 tone RAM。

set -euo pipefail

ROOT="${ZX300_PEQ_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ADB="${ADB:-/mnt/e/Downloads/platform-tools/adb.exe}"
KO="${KO:-$ROOT/kernel_modules/cxd3778gf_tone_apply/cxd3778gf_tone_apply.ko}"
REMOTE="${REMOTE:-/data/local/tmp/cxd3778gf_tone_apply.ko}"

cd "$ROOT"
test -f "$KO"

wait_shell() {
  local n
  for n in $(seq 1 30); do
    if "$ADB" shell true >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  "$ADB" devices -l
  echo "ADB shell not ready" >&2
  return 1
}

"$ADB" start-server >/dev/null
"$ADB" wait-for-device
"$ADB" push "$KO" "$REMOTE"
wait_shell
"$ADB" shell "rmmod cxd3778gf_tone_apply 2>/dev/null || true"
wait_shell
"$ADB" shell "insmod '$REMOTE'"
wait_shell
"$ADB" shell "cat /proc/cxd3778gf_tone_apply"
"$ADB" shell "dmesg | grep 'cxd3778gf_tone_apply' | tail -30"
