#!/usr/bin/env bash

# 应用 ZX300A BL3 “RBJ 起点 + 1-6 kHz 加权二次优化” all-target table，
# 并通过 cxd3778gf_tone_apply kmod 手动刷入 CXD3778GF tone RAM。
#
# 前置条件：
#   bash experiments/reproduce/15_bl3_rbj_refine_sensitive_zx300a_all_targets.sh
#   bash experiments/reproduce/72_build_cxd3778gf_tone_apply_module.sh
#   bash experiments/reproduce/97_install_cxd3778gf_tone_apply_module.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

EXPERIMENT_NAME="${EXPERIMENT_NAME:-bl3-zx300a-rbj-refine-sensitive-all-targets}"
TABLE="${TABLE:-samples/autoeq/${EXPERIMENT_NAME}/full-table/tc_127x.${EXPERIMENT_NAME}.tbl}"
REMOTE="${REMOTE:-/contents/wampy_probe/peq_apply/tc_127x.${EXPERIMENT_NAME}.tbl}"
READBACK="${READBACK:-samples/autoeq/${EXPERIMENT_NAME}/proc_tct_after_apply_and_tone_ram.bin}"

need_file "$TABLE"

"$ADB" push "$TABLE" "$REMOTE"
"$ADB" shell "cat '$REMOTE' > /proc/icx_audio_cxd3778gf_data/tct"
"$ADB" pull /proc/icx_audio_cxd3778gf_data/tct "$READBACK"
"$PYTHON" - "$TABLE" "$READBACK" <<'PY'
from pathlib import Path
import hashlib
import sys

table = Path(sys.argv[1])
readback = Path(sys.argv[2])
body = table.read_bytes()[:-8]
got = readback.read_bytes()
print("expected_body_md5", hashlib.md5(body).hexdigest())
print("readback_md5", hashlib.md5(got).hexdigest())
print("readback_matches", body == got)
if body != got:
    raise SystemExit("ZX300A refined BL3 tct readback mismatch")
PY

"$ADB" shell "echo apply > /proc/cxd3778gf_tone_apply"
"$ADB" shell "cat /proc/cxd3778gf_tone_apply"
"$ADB" shell "dmesg | grep 'cxd3778gf_tone_apply' | tail -30"
