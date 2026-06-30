#!/usr/bin/env bash

# 复现实验通用配置。
# 所有脚本都从 WSL 内的研究目录运行，Windows 目录只作为归档，不参与读写。

set -euo pipefail

ROOT="${ZX300_PEQ_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PYTHON="${PYTHON:-python3}"
TORCH_PYTHON="${TORCH_PYTHON:-/home/neoncloud/miniconda3/envs/pytorch/bin/python}"
ADB="${ADB:-/mnt/e/Downloads/platform-tools/adb.exe}"

BASE_TABLE="${BASE_TABLE:-backups/tc_1291.tbl}"
TARGET_WAV="${TARGET_WAV:-samples/autoeq/blessing3-mp48000/source/Moondrop Blessing 3 minimum phase 48000Hz.wav}"
AUTOEQ_PEQ="${AUTOEQ_PEQ:-external/autoeq/results/crinacle/Bruel & Kjaer 4620 in-ear/Moondrop Blessing 3/Moondrop Blessing 3 ParametricEQ.txt}"
AUTOEQ_PEQ_LOCAL="${AUTOEQ_PEQ_LOCAL:-samples/autoeq/blessing3/source/Moondrop Blessing 3 ParametricEQ.txt}"

cd "$ROOT"

need_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "缺少文件：$path" >&2
    exit 1
  fi
}

need_python() {
  local exe="$1"
  if [[ ! -x "$exe" && -z "$(command -v "$exe" 2>/dev/null)" ]]; then
    echo "找不到 Python：$exe" >&2
    exit 1
  fi
}
