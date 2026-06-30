#!/usr/bin/env python3
"""Inspect and build Sony CXD3778GF tone-control table blobs.

A full table file is 9 * 320 bytes followed by the stock 8-byte checksum
(sum32, xor32 little-endian). The kernel proc node /proc/icx_audio_cxd3778gf_data/tct
returns only the 2880-byte body; writes require body + checksum.
"""

import argparse
import hashlib
import struct
from pathlib import Path

TABLE_NAMES = [
    "nh",
    "ng",
    "nnw500",
    "nnw750",
    "nnc31",
    "sg",
    "snw500",
    "snw750",
    "snc31",
]
CHUNK_SIZE = 320
BODY_SIZE = CHUNK_SIZE * len(TABLE_NAMES)
CHECKSUM_SIZE = 8


def checksum(body: bytes):
    s = sum(body) & 0xFFFFFFFF
    x = 0
    for i, value in enumerate(body):
        x ^= (value << ((i % 4) * 8)) & 0xFFFFFFFF
    return s, x


def read_table(path: Path):
    data = path.read_bytes()
    if len(data) == BODY_SIZE:
        return data, None
    if len(data) == BODY_SIZE + CHECKSUM_SIZE:
        body = data[:-CHECKSUM_SIZE]
        expected = struct.unpack_from("<II", data, BODY_SIZE)
        return body, expected
    raise SystemExit(f"{path}: expected {BODY_SIZE} or {BODY_SIZE + CHECKSUM_SIZE} bytes, got {len(data)}")


def read_chunk(path: Path):
    data = path.read_bytes()
    if len(data) == CHUNK_SIZE:
        return data
    if len(data) == CHUNK_SIZE + CHECKSUM_SIZE:
        body = data[:-CHECKSUM_SIZE]
        expected = struct.unpack_from("<II", data, CHUNK_SIZE)
        actual = checksum(body)
        if actual != expected:
            raise SystemExit(
                f"{path}: chunk checksum mismatch: "
                f"actual sum=0x{actual[0]:08x} xor=0x{actual[1]:08x}, "
                f"expected sum=0x{expected[0]:08x} xor=0x{expected[1]:08x}"
            )
        return body
    raise SystemExit(
        f"{path}: expected {CHUNK_SIZE} or {CHUNK_SIZE + CHECKSUM_SIZE} bytes, got {len(data)}"
    )


def inspect(path: Path):
    body, expected = read_table(path)
    actual = checksum(body)
    print(f"file: {path}")
    print(f"body_size: {len(body)}")
    print(f"body_md5: {hashlib.md5(body).hexdigest()}")
    print(f"checksum: sum=0x{actual[0]:08x} xor=0x{actual[1]:08x}")
    if expected is not None:
        print(f"expected: sum=0x{expected[0]:08x} xor=0x{expected[1]:08x}")
        print(f"checksum_ok: {actual == expected}")
    for index, name in enumerate(TABLE_NAMES):
        chunk = body[index * CHUNK_SIZE:(index + 1) * CHUNK_SIZE]
        print(f"chunk[{index}:{name}]: md5={hashlib.md5(chunk).hexdigest()} nonzero={sum(1 for b in chunk if b)}")


def add_checksum(in_path: Path, out_path: Path):
    data = in_path.read_bytes()
    if len(data) in (BODY_SIZE + CHECKSUM_SIZE, CHUNK_SIZE + CHECKSUM_SIZE):
        body = data[:-CHECKSUM_SIZE]
    else:
        body = data
    if len(body) not in (CHUNK_SIZE, BODY_SIZE):
        raise SystemExit(f"{in_path}: expected {CHUNK_SIZE}, {CHUNK_SIZE + CHECKSUM_SIZE}, {BODY_SIZE}, or {BODY_SIZE + CHECKSUM_SIZE} bytes, got {len(data)}")
    out_path.write_bytes(body + struct.pack("<II", *checksum(body)))


def split(path: Path, out_dir: Path):
    body, _ = read_table(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(TABLE_NAMES):
        (out_dir / f"tct_{name}.bin").write_bytes(body[index * CHUNK_SIZE:(index + 1) * CHUNK_SIZE])


def replace_chunk(base_path: Path, name: str, chunk_path: Path, out_path: Path):
    body, _ = read_table(base_path)
    chunk = read_chunk(chunk_path)
    chunks = [body[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE] for i in range(len(TABLE_NAMES))]
    chunks[TABLE_NAMES.index(name)] = chunk
    new_body = b"".join(chunks)
    out_path.write_bytes(new_body + struct.pack("<II", *checksum(new_body)))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("table", type=Path)
    p = sub.add_parser("add-checksum")
    p.add_argument("body", type=Path)
    p.add_argument("out", type=Path)
    p = sub.add_parser("split")
    p.add_argument("table", type=Path)
    p.add_argument("out_dir", type=Path)
    p = sub.add_parser("replace-chunk")
    p.add_argument("base_table", type=Path)
    p.add_argument("name", choices=TABLE_NAMES)
    p.add_argument("chunk", type=Path)
    p.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.cmd == "inspect":
        inspect(args.table)
    elif args.cmd == "add-checksum":
        add_checksum(args.body, args.out)
    elif args.cmd == "split":
        split(args.table, args.out_dir)
    elif args.cmd == "replace-chunk":
        replace_chunk(args.base_table, args.name, args.chunk, args.out)


if __name__ == "__main__":
    main()
