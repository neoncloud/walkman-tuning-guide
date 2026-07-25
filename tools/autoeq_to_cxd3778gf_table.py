#!/usr/bin/env python3
"""Build a full CXD3778GF tc_*.tbl tone table from an AutoEq-style PEQ file."""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

import autoeq_to_cxd3778gf_peq as peq  # noqa: E402
import cxd3778gf_tct_tool as tct  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="AutoEq-style filter text")
    parser.add_argument("output", type=Path, help="output full 2888-byte tc_*.tbl")
    parser.add_argument("--base-table", type=Path, required=True, help="stock 2880/2888-byte tc_*.tbl")
    parser.add_argument("--target", choices=tct.TABLE_NAMES, default="sg")
    parser.add_argument(
        "--fs441",
        type=float,
        default=peq.DEFAULT_TONE_FS_441,
        help="tone-DSP coefficient rate for the 44.1k-family half (default: 176400)",
    )
    parser.add_argument(
        "--fs48",
        type=float,
        default=peq.DEFAULT_TONE_FS_48,
        help="tone-DSP coefficient rate for the 48k-family half (default: 192000)",
    )
    parser.add_argument(
        "--filter-strategy",
        choices=("first", "largest", "wide", "greedy", "best"),
        default="first",
        help="how to choose filters when input has more than five",
    )
    parser.add_argument("--max-sections", type=int, default=peq.SECTIONS)
    parser.add_argument(
        "--headroom-db",
        type=float,
        default=0.0,
        help="minimum peak headroom after recalculating response at the tone-DSP clocks",
    )
    parser.add_argument(
        "--preserve-preamp",
        action="store_true",
        help="do not add attenuation when the input preamp is insufficient at the tone-DSP clocks",
    )
    args = parser.parse_args()

    requested_preamp, filters = peq.parse_autoeq(args.input.read_text())
    preamp = requested_preamp
    if not args.preserve_preamp:
        preamp = peq.limit_preamp_for_headroom(
            filters,
            requested_preamp,
            args.fs441,
            args.fs48,
            args.filter_strategy,
            args.max_sections,
            args.headroom_db,
        )
        if preamp < requested_preamp - 1e-9:
            print(
                f"warning: adjusted preamp from {requested_preamp:+.3f} dB "
                f"to {preamp:+.3f} dB for {args.headroom_db:.3f} dB headroom"
            )
    chunk = peq.render(
        filters,
        preamp,
        args.fs441,
        args.fs48,
        with_checksum=False,
        filter_strategy=args.filter_strategy,
        max_sections=args.max_sections,
    )
    if len(chunk) != tct.CHUNK_SIZE:
        raise SystemExit(f"internal error: generated chunk is {len(chunk)} bytes")

    body, _expected = tct.read_table(args.base_table)
    chunks = [body[i * tct.CHUNK_SIZE:(i + 1) * tct.CHUNK_SIZE] for i in range(len(tct.TABLE_NAMES))]
    target_index = tct.TABLE_NAMES.index(args.target)
    old_md5 = hashlib.md5(chunks[target_index]).hexdigest()
    new_md5 = hashlib.md5(chunk).hexdigest()
    chunks[target_index] = chunk
    new_body = b"".join(chunks)
    args.output.write_bytes(new_body + struct.pack("<II", *tct.checksum(new_body)))

    print(
        f"requested_preamp_db={requested_preamp} applied_preamp_db={preamp} "
        f"filters={len(filters)} strategy={args.filter_strategy} "
        f"max_sections={args.max_sections} fs441={args.fs441:g} fs48={args.fs48:g} "
        f"target={args.target} written={args.output} bytes={args.output.stat().st_size}"
    )
    print(f"target_old_md5={old_md5}")
    print(f"target_new_md5={new_md5}")


if __name__ == "__main__":
    main()
