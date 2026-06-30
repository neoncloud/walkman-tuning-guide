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
    parser.add_argument("--fs441", type=float, default=44100.0)
    parser.add_argument("--fs48", type=float, default=48000.0)
    parser.add_argument(
        "--filter-strategy",
        choices=("first", "largest", "wide", "greedy", "best"),
        default="first",
        help="how to choose filters when input has more than five",
    )
    parser.add_argument("--max-sections", type=int, default=peq.SECTIONS)
    args = parser.parse_args()

    preamp, filters = peq.parse_autoeq(args.input.read_text())
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
        f"preamp_db={preamp} filters={len(filters)} strategy={args.filter_strategy} "
        f"max_sections={args.max_sections} target={args.target} written={args.output} bytes={args.output.stat().st_size}"
    )
    print(f"target_old_md5={old_md5}")
    print(f"target_new_md5={new_md5}")


if __name__ == "__main__":
    main()
