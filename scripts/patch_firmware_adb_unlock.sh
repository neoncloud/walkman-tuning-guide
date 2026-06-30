#!/usr/bin/env bash
set -euo pipefail

APPLY=0
FIRMWARE=
UPGTOOL=
OUT_DIR=

usage() {
  cat <<'USAGE'
Usage:
  scripts/patch_firmware_adb_unlock.sh --firmware NW_WM_FW.UPG --upgtool upgtool-v3.exe [--out-dir out/adb-unlock] [--apply]

The script never edits the original firmware package. Without --apply it only
prints the planned workspace and commands.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --firmware) FIRMWARE=$2; shift 2 ;;
    --upgtool) UPGTOOL=$2; shift 2 ;;
    --out-dir) OUT_DIR=$2; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$FIRMWARE" && -f "$FIRMWARE" ]] || { echo "missing --firmware" >&2; exit 2; }
[[ -n "$UPGTOOL" && -f "$UPGTOOL" ]] || { echo "missing --upgtool" >&2; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/out/adb-unlock}"
WORK="$OUT_DIR/work"
PATCHED="$OUT_DIR/patched"

echo "firmware: $FIRMWARE"
echo "upgtool:  $UPGTOOL"
echo "work:     $WORK"
echo "patched:  $PATCHED"

if [[ "$APPLY" -ne 1 ]]; then
  echo "dry run only; add --apply to copy, unpack, patch, and repack"
  exit 0
fi

mkdir -p "$WORK" "$PATCHED"
cp "$FIRMWARE" "$WORK/original.UPG"

echo "Unpack the firmware with your upgtool, then place unpacked files under:"
echo "  $WORK/unpacked"
echo
echo "This repository intentionally does not encode a universal upgtool command,"
echo "because command-line syntax differs between leaked/community builds."
echo "After unpacking, run this script again with UNPACKED_DIR=$WORK/unpacked."

UNPACKED_DIR="${UNPACKED_DIR:-}"
if [[ -z "$UNPACKED_DIR" || ! -d "$UNPACKED_DIR" ]]; then
  exit 0
fi

candidate="$(grep -RIl 'adbd\|setprop\|persist.sys.usb\|install' "$UNPACKED_DIR" | head -1 || true)"
[[ -n "$candidate" ]] || { echo "no candidate installer script found" >&2; exit 1; }

python3 - "$candidate" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(errors="ignore")
begin = "# Walkman tuning guide ADB unlock begin"
end = "# Walkman tuning guide ADB unlock end"
block = f"""
{begin}
setprop persist.service.adb.enable 1
setprop persist.sys.usb.config adb
start adbd
{end}
"""
if begin not in text:
    path.write_text(text.rstrip() + "\n" + block)
print(path)
PY

echo "Patched candidate installer script: $candidate"
echo "Now repack $UNPACKED_DIR with your upgtool and write the new UPG into $PATCHED."
