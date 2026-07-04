#!/usr/bin/env bash
set -euo pipefail

ADB=${ADB:-/mnt/e/Downloads/platform-tools/adb.exe}
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR=${WORKDIR:-$ROOT}
REMOTE_DIR=${REMOTE_DIR:-/contents/wampy_probe/peq_apply}
TARGET=sg
RESTORE=0
INPUT=
FILTER_STRATEGY=first
MAX_SECTIONS=5

usage() {
  cat <<USAGE
Usage:
  $0 --input autoeq.txt [--target sg] [--filter-strategy first|largest|wide|greedy|best] [--max-sections 1..5]
  $0 --restore [--target sg]

Targets map to /proc/icx_audio_cxd3778gf_data/tct_<target>.
Common target for normal headphone output on A50 is sg.
Set ADB=/path/to/adb.exe to override the default.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input) INPUT=$2; shift 2 ;;
    --target) TARGET=$2; shift 2 ;;
    --restore) RESTORE=1; shift ;;
    --filter-strategy) FILTER_STRATEGY=$2; shift 2 ;;
    --max-sections) MAX_SECTIONS=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$TARGET" in
  nh|ng|nnw500|nnw750|nnc31|sg|snw500|snw750|snc31) ;;
  *) echo "invalid target: $TARGET" >&2; exit 2 ;;
esac

case "$FILTER_STRATEGY" in
  first|largest|wide|greedy|best) ;;
  *) echo "invalid filter strategy: $FILTER_STRATEGY" >&2; exit 2 ;;
esac

case "$MAX_SECTIONS" in
  1|2|3|4|5) ;;
  *) echo "invalid max sections: $MAX_SECTIONS" >&2; exit 2 ;;
esac

PROC_NODE=/proc/icx_audio_cxd3778gf_data/tct_${TARGET}
LOCAL_BACKUP="$WORKDIR/device-dumps/live-backups/tct_${TARGET}.bin"
LOCAL_BLOB="$WORKDIR/device-dumps/live-backups/peq_${TARGET}.proc"
LOCAL_BACKUP_PROC="$WORKDIR/device-dumps/live-backups/tct_${TARGET}.backup.proc"
LOCAL_READBACK="$WORKDIR/device-dumps/live-backups/tct_${TARGET}.readback.bin"
REMOTE_BACKUP="$REMOTE_DIR/tct_${TARGET}.backup.proc"
REMOTE_BLOB="$REMOTE_DIR/peq_${TARGET}.proc"

mkdir -p "$(dirname "$LOCAL_BACKUP")"

if [[ "$RESTORE" -eq 1 ]]; then
  if [[ ! -f "$LOCAL_BACKUP" ]]; then
    echo "no local backup found for target $TARGET: $LOCAL_BACKUP" >&2
    echo "restore can only use a previous backup; refusing to overwrite it from the device" >&2
    exit 1
  fi
  "$WORKDIR/tools/cxd3778gf_tct_tool.py" add-checksum "$LOCAL_BACKUP" "$LOCAL_BACKUP_PROC"
  "$ADB" shell "mkdir -p '$REMOTE_DIR'"
  "$ADB" push "$LOCAL_BACKUP_PROC" "$REMOTE_BACKUP" >/dev/null
  "$ADB" shell "cat '$REMOTE_BACKUP' > '$PROC_NODE'"
  "$ADB" shell "cat '$PROC_NODE' > '$REMOTE_DIR/tct_${TARGET}.readback.body'"
  "$ADB" pull "$REMOTE_DIR/tct_${TARGET}.readback.body" "$LOCAL_READBACK" >/dev/null
  cmp -s "$LOCAL_BACKUP" "$LOCAL_READBACK"
  echo "restored $PROC_NODE from $LOCAL_BACKUP and verified readback"
  exit 0
fi

"$ADB" shell "mkdir -p '$REMOTE_DIR'; cat '$PROC_NODE' > '$REMOTE_DIR/tct_${TARGET}.backup.body'"
if [[ -f "$LOCAL_BACKUP" ]]; then
  echo "keeping existing local backup: $LOCAL_BACKUP"
  "$ADB" pull "$REMOTE_DIR/tct_${TARGET}.backup.body" "$WORKDIR/device-dumps/live-backups/tct_${TARGET}.current-before-apply.bin" >/dev/null
else
  "$ADB" pull "$REMOTE_DIR/tct_${TARGET}.backup.body" "$LOCAL_BACKUP" >/dev/null
  echo "created local backup: $LOCAL_BACKUP"
fi
"$WORKDIR/tools/cxd3778gf_tct_tool.py" add-checksum "$LOCAL_BACKUP" "$LOCAL_BACKUP_PROC"
"$ADB" push "$LOCAL_BACKUP_PROC" "$REMOTE_BACKUP" >/dev/null

if [[ -z "$INPUT" ]]; then
  echo "--input is required unless --restore is used" >&2
  usage >&2
  exit 2
fi

"$WORKDIR/tools/autoeq_to_cxd3778gf_peq.py" "$INPUT" "$LOCAL_BLOB" --filter-strategy "$FILTER_STRATEGY" --max-sections "$MAX_SECTIONS"
"$ADB" push "$LOCAL_BLOB" "$REMOTE_BLOB" >/dev/null
"$ADB" shell "cat '$REMOTE_BLOB' > '$PROC_NODE'"
"$ADB" shell "cat '$PROC_NODE' > '$REMOTE_DIR/tct_${TARGET}.readback.body'"
"$ADB" pull "$REMOTE_DIR/tct_${TARGET}.readback.body" "$LOCAL_READBACK" >/dev/null
cmp -s <(head -c 320 "$LOCAL_BLOB") "$LOCAL_READBACK"
echo "applied PEQ to $PROC_NODE and verified readback"
echo "backup body: $LOCAL_BACKUP"
echo "restore with: $0 --restore --target $TARGET"
