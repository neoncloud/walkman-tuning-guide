#!/usr/bin/env bash

# 使用 minimum-phase WAV 目标，复现安全基线 RBJ 5 段 IIR 拟合。
# 输出包括 raw chunk、带校验 chunk、完整 tc_1291 table、CSV/SVG 曲线和 JSON 元数据。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

need_file "$TARGET_WAV"
need_file "$BASE_TABLE"

OUT_DIR="${OUT_DIR:-samples/autoeq/blessing3-rbj-refactor}"
EXPERIMENT_NAME="${EXPERIMENT_NAME:-blessing3-rbj-refactor}"

mkdir -p "$OUT_DIR/chunks" "$OUT_DIR/full-table" "$OUT_DIR/plots"

"$PYTHON" tools/fit_cxd3778gf_iir_to_wav.py \
  "$TARGET_WAV" \
  "$OUT_DIR/full-table/tc_1291.${EXPERIMENT_NAME}-ng-sg.tbl" \
  --base-table "$BASE_TABLE" \
  --chunk "$OUT_DIR/chunks/${EXPERIMENT_NAME}.bin" \
  --metadata "$OUT_DIR/${EXPERIMENT_NAME}.json" \
  --plot-svg "$OUT_DIR/plots/${EXPERIMENT_NAME}.svg" \
  --plot-csv "$OUT_DIR/plots/${EXPERIMENT_NAME}.csv" \
  --targets ng,sg

"$PYTHON" tools/cxd3778gf_tct_tool.py inspect "$OUT_DIR/full-table/tc_1291.${EXPERIMENT_NAME}-ng-sg.tbl"
