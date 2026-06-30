#!/usr/bin/env bash

# 移除 cxd3778gf_tone_apply 的开机自动加载配置。
# 默认保留 /contents/wampy_probe/peq_apply/auto_tct.tbl；如需删除，设置 REMOVE_AUTO_TCT=1。

set -euo pipefail

ADB="${ADB:-/mnt/e/Downloads/platform-tools/adb.exe}"
BOOT="/system/bin/bootswitcher.sh"
BOOT_BAK="/system/bin/bootswitcher.sh.cxd3778gf_tone_apply_bak"
SYSTEM_KO="/system/lib/modules/cxd3778gf_tone_apply.ko"
AUTO_TCT="/data/local/cxd3778gf_tone/auto_tct.tbl"

"$ADB" start-server >/dev/null
"$ADB" wait-for-device
"$ADB" shell "mount -o remount,rw /system"
"$ADB" shell "if [ -f '$BOOT_BAK' ]; then cp '$BOOT_BAK' '$BOOT' && chmod 0755 '$BOOT' && chown root.shell '$BOOT'; fi"
"$ADB" shell "rm -f '$SYSTEM_KO'"
"$ADB" shell "mount -o remount,ro /system" || true

if [[ "${REMOVE_AUTO_TCT:-0}" == "1" ]]; then
  "$ADB" shell "rm -f '$AUTO_TCT'"
fi

"$ADB" shell "rmmod cxd3778gf_tone_apply 2>/dev/null || true"
"$ADB" shell "ls -la '$BOOT' '$BOOT_BAK' 2>/dev/null; ls -la '$SYSTEM_KO' 2>/dev/null || true"
