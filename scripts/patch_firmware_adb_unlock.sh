#!/usr/bin/env bash
set -euo pipefail

APPLY=0
FIRMWARE="${FIRMWARE:-}"
UPGTOOL="${UPGTOOL:-}"
OUT_DIR=

usage() {
  cat <<'USAGE'
Usage:
  scripts/patch_firmware_adb_unlock.sh [--firmware NW_WM_FW.UPG] [--upgtool upgtool-v3.exe] [--out-dir out/adb-unlock] [--apply]

Without --apply, the script only prints the planned workspace and candidate
files. With --apply, it copies the firmware, asks the user to unpack it when
needed, patches one installer script with an ADB unlock block, and prints the
repack/replace steps.

Environment:
  FIRMWARE=/path/to/NW_WM_FW.UPG
  UPGTOOL=/path/to/upgtool-v3.exe
  UNPACKED_DIR=/path/to/unpacked/firmware
USAGE
}

find_first_file() {
  local pattern=$1
  shift
  local dir
  for dir in "$@"; do
    [[ -d "$dir" ]] || continue
    find "$dir" -maxdepth 3 -type f -iname "$pattern" 2>/dev/null | head -1
  done
}

prompt_path() {
  local label=$1
  local current=$2
  if [[ -n "$current" ]]; then
    printf '%s\n' "$current"
    return
  fi
  read -r -p "$label: " current
  printf '%s\n' "$current"
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

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/out/adb-unlock}"
WORK="$OUT_DIR/work"
PATCHED="$OUT_DIR/patched"

if [[ -z "$FIRMWARE" ]]; then
  FIRMWARE="$(find_first_file '*.UPG' "$PWD" "$HOME/Downloads" /mnt/e/Downloads /mnt/d/Downloads || true)"
fi
if [[ -z "$UPGTOOL" ]]; then
  UPGTOOL="$(find_first_file 'upgtool*.exe' "$PWD" "$HOME/Downloads" /mnt/e/Downloads /mnt/d/Downloads || true)"
fi

if [[ -z "$FIRMWARE" || ! -f "$FIRMWARE" ]]; then
  FIRMWARE="$(prompt_path 'Firmware package path' "$FIRMWARE")"
fi
if [[ -z "$UPGTOOL" || ! -f "$UPGTOOL" ]]; then
  UPGTOOL="$(prompt_path 'upgtool executable path' "$UPGTOOL")"
fi

[[ -f "$FIRMWARE" ]] || { echo "firmware not found: $FIRMWARE" >&2; exit 2; }
[[ -f "$UPGTOOL" ]] || { echo "upgtool not found: $UPGTOOL" >&2; exit 2; }

cat <<EOF
Firmware: $FIRMWARE
upgtool:  $UPGTOOL
work:     $WORK
patched:  $PATCHED
mode:     $([[ "$APPLY" -eq 1 ]] && echo apply || echo dry-run)
EOF

if [[ "$APPLY" -ne 1 ]]; then
  cat <<'EOF'

Dry-run only. Re-run with --apply after checking the paths.
The original firmware will not be modified in place.
EOF
  exit 0
fi

mkdir -p "$WORK" "$PATCHED"
cp -f "$FIRMWARE" "$WORK/original.UPG"

UNPACKED_DIR="${UNPACKED_DIR:-$WORK/unpacked}"
if [[ ! -d "$UNPACKED_DIR" ]]; then
  cat <<EOF

Next step:
  1. Use your upgtool build to unpack:
       $WORK/original.UPG
  2. Put the unpacked firmware tree at:
       $UNPACKED_DIR
  3. Re-run this script with the same arguments and --apply.

The repository does not hard-code one universal upgtool command because
community upgtool builds use different CLI syntax.
EOF
  exit 0
fi

mapfile -t candidates < <(grep -RIlE 'adbd|persist\.sys\.usb|setprop|install|update' "$UNPACKED_DIR" 2>/dev/null | head -20)
if [[ "${#candidates[@]}" -eq 0 ]]; then
  echo "no candidate installer script found under $UNPACKED_DIR" >&2
  exit 1
fi

echo "Candidate installer scripts:"
for i in "${!candidates[@]}"; do
  printf '  [%d] %s\n' "$i" "${candidates[$i]}"
done

choice=0
read -r -p "Patch which script? [0] " choice_input || true
if [[ -n "${choice_input:-}" ]]; then
  choice=$choice_input
fi
[[ "$choice" =~ ^[0-9]+$ && "$choice" -lt "${#candidates[@]}" ]] || { echo "invalid choice" >&2; exit 2; }

candidate="${candidates[$choice]}"
python3 - "$candidate" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = path.read_bytes()
text = data.decode("utf-8", errors="ignore")
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
    path.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
print(path)
PY

cat <<EOF

Patched candidate installer script:
  $candidate

Now repack:
  $UNPACKED_DIR

Write the repacked firmware into:
  $PATCHED

Then replace the firmware file used by the official installer with the patched
copy. Keep the original firmware package untouched for recovery.
EOF
