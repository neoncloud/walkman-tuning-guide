#!/usr/bin/env bash

# 按 ud505_hook 的方式，把 cxd3778gf_tone_apply.ko 安装为开机自动加载。
#
# 行为：
# - 把 .ko 安装到 /system/lib/modules/cxd3778gf_tone_apply.ko。
# - 备份 /system/bin/bootswitcher.sh。
# - 在 bootswitcher.sh 末尾追加自动加载逻辑。
# - 如果 /data/local/cxd3778gf_tone/auto_tct.tbl 存在，开机时先写完整
#   /proc/icx_audio_cxd3778gf_data/tct，再强制刷入 table 5 / tct_sg。
# - 如果 auto_tct.tbl 不存在，则只加载 kmod，并对当前内存 table 执行 apply。

set -euo pipefail

ROOT="${ZX300_PEQ_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ADB="${ADB:-/mnt/e/Downloads/platform-tools/adb.exe}"
PYTHON="${PYTHON:-python3}"
KO="${KO:-$ROOT/kernel_modules/cxd3778gf_tone_apply/cxd3778gf_tone_apply.ko}"
REMOTE_KO="/data/local/tmp/cxd3778gf_tone_apply.ko"
SYSTEM_KO="/system/lib/modules/cxd3778gf_tone_apply.ko"
BOOT="/system/bin/bootswitcher.sh"
BOOT_BAK="/system/bin/bootswitcher.sh.cxd3778gf_tone_apply_bak"
WORK="$ROOT/backups/zx300a-autoload"

cd "$ROOT"
test -f "$KO"
mkdir -p "$WORK"

"$ADB" start-server >/dev/null
"$ADB" wait-for-device
"$ADB" pull "$BOOT" "$WORK/bootswitcher.sh.before_cxd3778gf_tone_apply"

"$PYTHON" - "$WORK/bootswitcher.sh.before_cxd3778gf_tone_apply" "$WORK/bootswitcher.sh.cxd3778gf_tone_apply" <<'PY'
from pathlib import Path
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text()
begin = "# CXD3778GF tone table apply support."
end = "# End CXD3778GF tone table apply support."
block = """\

# CXD3778GF tone table apply support.
# Load the TYPE_Z tone-RAM helper and apply a persistent table when present.
CXD3778GF_TONE_MOD=/system/lib/modules/cxd3778gf_tone_apply.ko
CXD3778GF_TONE_PROC=/proc/cxd3778gf_tone_apply
CXD3778GF_TCT_PROC=/proc/icx_audio_cxd3778gf_data/tct
CXD3778GF_AUTO_TCT=/data/local/cxd3778gf_tone/auto_tct.tbl
if [ -f "$CXD3778GF_TONE_MOD" ]; then
    if [ ! -d /sys/module/cxd3778gf_tone_apply ]; then
        /bin/insmod "$CXD3778GF_TONE_MOD" 2>/dev/null
    fi
    CXD3778GF_WAIT=0
    while [ "$CXD3778GF_WAIT" -lt 20 ]; do
        if [ -f "$CXD3778GF_TONE_PROC" ] && [ -f "$CXD3778GF_TCT_PROC" ]; then
            break
        fi
        sleep 1
        CXD3778GF_WAIT=`expr "$CXD3778GF_WAIT" + 1`
    done
    if [ -f "$CXD3778GF_TONE_PROC" ]; then
        if [ -f "$CXD3778GF_AUTO_TCT" ] && [ -f "$CXD3778GF_TCT_PROC" ]; then
            cat "$CXD3778GF_AUTO_TCT" > "$CXD3778GF_TCT_PROC" 2>/dev/null
            echo table 5 > "$CXD3778GF_TONE_PROC" 2>/dev/null
        else
            echo apply > "$CXD3778GF_TONE_PROC" 2>/dev/null
        fi
    fi
fi
# End CXD3778GF tone table apply support.
"""

if begin in text and end in text:
    pre = text.split(begin, 1)[0].rstrip()
    post = text.split(end, 1)[1].lstrip()
    text = pre + block + ("\n" + post if post else "")
else:
    text = text.rstrip() + block
dst.write_text(text)
PY

"$ADB" push "$KO" "$REMOTE_KO"
"$ADB" push "$WORK/bootswitcher.sh.cxd3778gf_tone_apply" /data/local/tmp/bootswitcher.sh.cxd3778gf_tone_apply

"$ADB" shell "mount -o remount,rw /system"
"$ADB" shell "test -f '$BOOT_BAK' || cp '$BOOT' '$BOOT_BAK'"
"$ADB" shell "cp '$REMOTE_KO' '$SYSTEM_KO' && chmod 0644 '$SYSTEM_KO' && chown root.root '$SYSTEM_KO'"
"$ADB" shell "cp /data/local/tmp/bootswitcher.sh.cxd3778gf_tone_apply '$BOOT' && chmod 0755 '$BOOT' && chown root.shell '$BOOT'"
"$ADB" shell "mount -o remount,ro /system" || true

"$ADB" shell "ls -la '$SYSTEM_KO' '$BOOT' '$BOOT_BAK'"
"$ADB" shell "grep -n 'CXD3778GF tone table apply support' '$BOOT'"
