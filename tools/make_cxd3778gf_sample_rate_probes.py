#!/usr/bin/env python3
"""生成用于反推 CXD3778GF tone-DSP 时钟和活动 RAM half 的完整 TBL。"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

import autoeq_to_cxd3778gf_peq as peq  # noqa: E402
import cxd3778gf_tct_tool as tct  # noqa: E402


def full_table_with_sg(chunk: bytes) -> bytes:
    """构造仅替换 sg chunk 的全 identity 2888-byte table。"""
    if len(chunk) != tct.CHUNK_SIZE:
        raise ValueError(f"probe chunk must be {tct.CHUNK_SIZE} bytes")
    chunks = [tct.make_identity_chunk() for _ in tct.TABLE_NAMES]
    chunks[tct.TABLE_NAMES.index("sg")] = chunk
    body = b"".join(chunks)
    return body + struct.pack("<II", *tct.checksum(body))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--common-reference-fs",
        type=float,
        default=48000.0,
        help="两个 half 共用探针的系数设计时钟",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    identity_path = args.output_dir / "identity.tbl"
    common_path = args.output_dir / "common_1khz_plus12_ref48k.tbl"
    bank_path = args.output_dir / "asymmetric_halves.tbl"

    tct.make_identity_table(identity_path)

    # 两个 half 完全相同。无论硬件选择哪一半，观察到的中心频率都只由
    # 实际 tone-DSP 时钟决定，可据此独立反推 DSP Fs。
    common_filter = peq.Filter("PK", 1000.0, 12.0, 1.0, 1)
    common_half = peq.render_half(
        [common_filter],
        args.common_reference_fs,
        0.0,
    )
    common_path.write_bytes(full_table_with_sg(common_half + common_half))

    # 两个 half 使用明显不同的曲线，用于实测当前播放通路读取哪一块 RAM。
    # 不能只凭源码中的 44.1/48 kHz 命名预设硬件一定会自动切换。
    half0_filter = peq.Filter("PK", 700.0, 12.0, 1.0, 1)
    half1_filter = peq.Filter("PK", 3000.0, -12.0, 1.0, 1)
    half0 = peq.render_half([half0_filter], peq.DEFAULT_TONE_FS_441, 0.0)
    half1 = peq.render_half([half1_filter], peq.DEFAULT_TONE_FS_48, 0.0)
    bank_path.write_bytes(full_table_with_sg(half0 + half1))

    metadata = {
        "identity_table": str(identity_path),
        "common_probe_table": str(common_path),
        "common_probe": {
            "filter": {
                "kind": "PK",
                "frequency_hz": 1000.0,
                "gain_db": 12.0,
                "q": 1.0,
            },
            "coefficient_reference_sample_rate_hz": args.common_reference_fs,
            "halves_identical": True,
        },
        "asymmetric_halves_table": str(bank_path),
        "half0_probe": {
            "filter": {
                "kind": "PK",
                "frequency_hz": 700.0,
                "gain_db": 12.0,
                "q": 1.0,
            },
            "coefficient_sample_rate_hz": peq.DEFAULT_TONE_FS_441,
        },
        "half1_probe": {
            "filter": {
                "kind": "PK",
                "frequency_hz": 3000.0,
                "gain_db": -12.0,
                "q": 1.0,
            },
            "coefficient_sample_rate_hz": peq.DEFAULT_TONE_FS_48,
        },
    }
    (args.output_dir / "probes.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for path in (identity_path, common_path, bank_path):
        tct.inspect(path)


if __name__ == "__main__":
    main()
