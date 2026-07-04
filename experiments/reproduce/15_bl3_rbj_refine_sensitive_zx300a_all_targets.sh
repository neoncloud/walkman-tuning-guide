#!/usr/bin/env bash

# ZX300A BL3 改进版 RBJ 实验：
# 先用原始 RBJ 5 段拟合得到稳定 IIR 起点，再从该起点继续直接优化，
# 并提高 1 kHz 到 6 kHz 人耳敏感频段的误差权重。
# 本脚本只生成文件，不写设备。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

BL3_TARGET_WAV="${BL3_TARGET_WAV:-tools/test/bl3.wav}"
BL3_TARGET_PEQ="${BL3_TARGET_PEQ:-tools/test/bl3.txt}"
ZX300A_BASE_TABLE="${ZX300A_BASE_TABLE:-backups/tc_127x.tbl}"
OUT_DIR="${OUT_DIR:-samples/autoeq/bl3-zx300a-rbj-refine-sensitive-all-targets}"
EXPERIMENT_NAME="${EXPERIMENT_NAME:-bl3-zx300a-rbj-refine-sensitive-all-targets}"
TARGET_CHUNKS="${TARGET_CHUNKS:-nh,ng,nnw500,nnw750,nnc31,sg,snw500,snw750,snc31}"
SENSITIVE_BAND="${SENSITIVE_BAND:-1000,6000}"
SENSITIVE_WEIGHT="${SENSITIVE_WEIGHT:-2.0}"
POINTS="${POINTS:-768}"

need_file "$BL3_TARGET_WAV"
need_file "$BL3_TARGET_PEQ"

if [[ ! -f "$ZX300A_BASE_TABLE" ]]; then
  mkdir -p "$(dirname "$ZX300A_BASE_TABLE")"
  "$PYTHON" tools/cxd3778gf_tct_tool.py make-identity "$ZX300A_BASE_TABLE"
  echo "created identity base table: $ZX300A_BASE_TABLE"
fi

mkdir -p "$OUT_DIR/chunks" "$OUT_DIR/full-table" "$OUT_DIR/plots"

"$PYTHON" tools/fit_cxd3778gf_iir_to_wav.py \
  "$BL3_TARGET_WAV" \
  "$OUT_DIR/full-table/tc_127x.${EXPERIMENT_NAME}.tbl" \
  --base-table "$ZX300A_BASE_TABLE" \
  --chunk "$OUT_DIR/chunks/${EXPERIMENT_NAME}.bin" \
  --metadata "$OUT_DIR/${EXPERIMENT_NAME}.json" \
  --autoeq-peq "$BL3_TARGET_PEQ" \
  --plot-svg "$OUT_DIR/plots/${EXPERIMENT_NAME}.svg" \
  --plot-csv "$OUT_DIR/plots/${EXPERIMENT_NAME}.csv" \
  --targets "$TARGET_CHUNKS" \
  --points "$POINTS" \
  --refine-from-rbj \
  --sensitive-band "$SENSITIVE_BAND" \
  --sensitive-weight "$SENSITIVE_WEIGHT"

"$PYTHON" tools/cxd3778gf_tct_tool.py inspect "$OUT_DIR/full-table/tc_127x.${EXPERIMENT_NAME}.tbl"
