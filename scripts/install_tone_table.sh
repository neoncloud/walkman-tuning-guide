#!/usr/bin/env bash
set -euo pipefail

# 常用安装入口：
# - A 系列：从 AutoEq 文本生成并直接写入指定 chunk。
# - ZX/WM：写入完整 table 后调用 cxd3778gf_tone_apply。

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADB="${ADB:-/mnt/e/Downloads/platform-tools/adb.exe}"
DEVICE_CLASS=
INPUT=
TABLE=
TARGET=sg
FILTER_STRATEGY=best
MAX_SECTIONS=5

usage() {
  cat <<'USAGE'
Usage:
  scripts/install_tone_table.sh --device-class a --input autoeq.txt [--target sg]
  scripts/install_tone_table.sh --device-class zx --table full-table.tbl

Options:
  --device-class a|zx|wm    Deployment path. "wm" uses the same helper-module path as "zx".
  --input autoeq.txt        AutoEq text profile for A-series direct write.
  --table full-table.tbl    Full 2888-byte table for ZX/WM helper-module path.
  --target name             A-series target chunk: sg, ng, nh, nnw500, nnw750, nnc31, snw500, snw750, snc31.
  --filter-strategy name    first, largest, wide, greedy, best. Default: best.
  --max-sections 1..5       Maximum PEQ sections for direct write. Default: 5.

Environment:
  ADB=/path/to/adb
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device-class) DEVICE_CLASS=$2; shift 2 ;;
    --input) INPUT=$2; shift 2 ;;
    --table) TABLE=$2; shift 2 ;;
    --target) TARGET=$2; shift 2 ;;
    --filter-strategy) FILTER_STRATEGY=$2; shift 2 ;;
    --max-sections) MAX_SECTIONS=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$DEVICE_CLASS" in
  a)
    [[ -n "$INPUT" && -f "$INPUT" ]] || { echo "--input autoeq.txt is required for A-series" >&2; exit 2; }
    exec bash "$ROOT/tools/apply_cxd3778gf_peq_adb.sh" \
      --input "$INPUT" \
      --target "$TARGET" \
      --filter-strategy "$FILTER_STRATEGY" \
      --max-sections "$MAX_SECTIONS"
    ;;
  zx|wm)
    [[ -n "$TABLE" && -f "$TABLE" ]] || { echo "--table full-table.tbl is required for ZX/WM" >&2; exit 2; }
    export ADB
    TABLE="$(cd "$(dirname "$TABLE")" && pwd)/$(basename "$TABLE")"
    REMOTE="/data/local/cxd3778gf_tone/manual_tct.tbl"
    "$ADB" shell "mkdir -p /data/local/cxd3778gf_tone"
    "$ADB" push "$TABLE" "$REMOTE"
    "$ADB" shell "cat '$REMOTE' > /proc/icx_audio_cxd3778gf_data/tct"
    "$ADB" shell "echo apply > /proc/cxd3778gf_tone_apply"
    "$ADB" shell "cat /proc/cxd3778gf_tone_apply"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
