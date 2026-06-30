#!/usr/bin/env bash

# 设置开机自动应用的完整 tct table。
# 默认使用当前推荐的 BL3 RBJ 敏感频段加权 all-target 表。
# 设置后会立即写入 proc 并 echo apply，方便不用重启也生效。

set -euo pipefail

ROOT="${ZX300_PEQ_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ADB="${ADB:-/mnt/e/Downloads/platform-tools/adb.exe}"
TABLE="${TABLE:-$ROOT/samples/autoeq/bl3-zx300a-rbj-refine-sensitive-all-targets/full-table/tc_127x.bl3-zx300a-rbj-refine-sensitive-all-targets.tbl}"
REMOTE_DIR="${REMOTE_DIR:-/data/local/cxd3778gf_tone}"
REMOTE_TABLE="$REMOTE_DIR/auto_tct.tbl"

test -f "$TABLE"

"$ADB" start-server >/dev/null
"$ADB" wait-for-device
"$ADB" shell "mkdir -p '$REMOTE_DIR'"
"$ADB" push "$TABLE" "$REMOTE_TABLE"
"$ADB" shell "cat '$REMOTE_TABLE' > /proc/icx_audio_cxd3778gf_data/tct"
"$ADB" shell "echo apply > /proc/cxd3778gf_tone_apply"
"$ADB" shell "cat /proc/cxd3778gf_tone_apply"
