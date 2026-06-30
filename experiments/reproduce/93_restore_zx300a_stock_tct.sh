#!/usr/bin/env bash

# 通过 ADB 恢复 ZX300A stock tc_127x.tbl 到完整 tct proc 节点。
# 这个脚本会写设备。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

ZX300A_BASE_TABLE="${ZX300A_BASE_TABLE:-backups/tc_127x.tbl}"
REMOTE="${REMOTE:-/contents/wampy_probe/peq_apply/tc_127x.stock.tbl}"
READBACK="${READBACK:-backups/proc_tct_after_restore.bin}"

need_file "$ZX300A_BASE_TABLE"

"$ADB" push "$ZX300A_BASE_TABLE" "$REMOTE"
"$ADB" shell "cat '$REMOTE' > /proc/icx_audio_cxd3778gf_data/tct"
mkdir -p "$(dirname "$READBACK")"
"$ADB" pull /proc/icx_audio_cxd3778gf_data/tct "$READBACK"
"$PYTHON" - "$ZX300A_BASE_TABLE" "$READBACK" <<'PY'
from pathlib import Path
import hashlib
import sys

table = Path(sys.argv[1])
readback = Path(sys.argv[2])
body = table.read_bytes()[:-8]
got = readback.read_bytes()
print("stock_body_md5", hashlib.md5(body).hexdigest())
print("readback_md5", hashlib.md5(got).hexdigest())
print("readback_matches", body == got)
if body != got:
    raise SystemExit("ZX300A stock restore readback mismatch")
PY
