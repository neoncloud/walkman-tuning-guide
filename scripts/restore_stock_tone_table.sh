#!/usr/bin/env bash
set -euo pipefail

# 常用还原入口。
# A 系列复用 direct-write 脚本保存的本地备份。
# ZX/WM 默认复用已验证的 ZX300A stock restore reproduce 脚本。

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE_CLASS=
TARGET=sg

usage() {
  cat <<'USAGE'
Usage:
  scripts/restore_stock_tone_table.sh --device-class a [--target sg]
  scripts/restore_stock_tone_table.sh --device-class zx
  scripts/restore_stock_tone_table.sh --device-class wm

Environment:
  ADB=/path/to/adb
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device-class) DEVICE_CLASS=$2; shift 2 ;;
    --target) TARGET=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$DEVICE_CLASS" in
  a)
    exec bash "$ROOT/tools/apply_cxd3778gf_peq_adb.sh" --restore --target "$TARGET"
    ;;
  zx|wm)
    exec bash "$ROOT/experiments/reproduce/93_restore_zx300a_stock_tct_and_tone_ram.sh"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
