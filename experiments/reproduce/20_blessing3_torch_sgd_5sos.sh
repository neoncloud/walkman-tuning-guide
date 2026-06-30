#!/usr/bin/env bash

# 复现当前听感和指标最好的 Torch 优化：5 个完整 SOS，无独立 pre-gain 段。
# 默认参数偏向稳定和可听安全；可通过 STARTS、STEPS、LR、DEVICE 覆盖。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

need_python "$TORCH_PYTHON"
need_file "$TARGET_WAV"
need_file "$BASE_TABLE"

OUT_DIR="${OUT_DIR:-samples/autoeq/blessing3-torch-sgd-5sos}"
EXPERIMENT_NAME="${EXPERIMENT_NAME:-blessing3-torch-sgd-5sos}"

mkdir -p "$OUT_DIR/chunks" "$OUT_DIR/full-table" "$OUT_DIR/plots"

"$TORCH_PYTHON" tools/fit_cxd3778gf_torch_sos_to_wav.py \
  "$TARGET_WAV" \
  "$OUT_DIR/full-table/tc_1291.${EXPERIMENT_NAME}-ng-sg.tbl" \
  --base-table "$BASE_TABLE" \
  --metadata "$OUT_DIR/${EXPERIMENT_NAME}.json" \
  --chunk "$OUT_DIR/chunks/${EXPERIMENT_NAME}.bin" \
  --plot-dir "$OUT_DIR/plots" \
  --autoeq-peq "$AUTOEQ_PEQ" \
  --layout sos5 \
  --sections 5 \
  --starts "${STARTS:-128}" \
  --steps "${STEPS:-3500}" \
  --lr "${LR:-0.03}" \
  --max-pole-radius "${MAX_POLE_RADIUS:-0.95}" \
  --max-section-peak-db "${MAX_SECTION_PEAK_DB:-8.0}" \
  --max-prefix-peak-db "${MAX_PREFIX_PEAK_DB:-4.0}" \
  --section-peak-weight "${SECTION_PEAK_WEIGHT:-0.5}" \
  --prefix-peak-weight "${PREFIX_PEAK_WEIGHT:-1.0}" \
  --radius-weight "${RADIUS_WEIGHT:-0.01}" \
  --device "${DEVICE:-cuda}" \
  --verbose

"$PYTHON" tools/cxd3778gf_tct_tool.py inspect "$OUT_DIR/full-table/tc_1291.${EXPERIMENT_NAME}-ng-sg.tbl"
