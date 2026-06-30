#!/usr/bin/env python3
"""Plot CXD3778GF tone-control table response as cascaded biquads.

Assumed 320-byte chunk layout:
  - two 160-byte halves, normally for 44.1 kHz and 48 kHz families
  - each half has 32 signed 40-bit big-endian Q37 words
  - first 25 words are five biquads: b0, b1, b2, -a1, -a2
"""

from __future__ import annotations

import argparse
import cmath
import csv
import math
from pathlib import Path


SCALE = 1 << 37
DEFAULT_CHUNKS = ("sg", "nnw500", "nnw750", "nnc31", "snw500", "snw750", "snc31")
CHUNK_SIZE = 320
CHECKSUM_SIZE = 8
COLORS = {
    "sg": "#222222",
    "nnw500": "#d13c3c",
    "nnw750": "#2563eb",
    "nnc31": "#16a34a",
    "snw500": "#eab308",
    "snw750": "#8b5cf6",
    "snc31": "#0f766e",
}
LABELS = {
    "sg": "general/identity",
    "nnw500": "NW500 normal",
    "nnw750": "NW750 normal",
    "nnc31": "NC31 normal",
    "snw500": "NW500 studio",
    "snw750": "NW750 studio",
    "snc31": "NC31 studio",
}


def s40be_q37(raw: bytes) -> float:
    value = int.from_bytes(raw, "big", signed=False)
    if value & (1 << 39):
        value -= 1 << 40
    return value / SCALE


def decode_sections(path: Path, half: int) -> list[list[float]]:
    data = path.read_bytes()
    if len(data) == CHUNK_SIZE + CHECKSUM_SIZE:
        data = data[:CHUNK_SIZE]
    if len(data) != CHUNK_SIZE:
        raise ValueError(
            f"{path} is {len(data)} bytes, expected one 320-byte chunk "
            f"or a 328-byte checksummed chunk"
        )
    offset = half * 160
    words = [s40be_q37(data[offset + i * 5 : offset + i * 5 + 5]) for i in range(32)]
    return [words[i * 5 : (i + 1) * 5] for i in range(5)]


def response_db(sections: list[list[float]], freq: float, fs: int) -> float:
    z1 = cmath.exp(-2j * math.pi * freq / fs)
    z2 = z1 * z1
    response = 1 + 0j
    for b0, b1, b2, neg_a1, neg_a2 in sections:
        numerator = b0 + b1 * z1 + b2 * z2
        denominator = 1 - neg_a1 * z1 - neg_a2 * z2
        response *= numerator / denominator
    magnitude = abs(response)
    return -240.0 if magnitude <= 1e-12 else 20 * math.log10(magnitude)


def logspace(start: float, stop: float, count: int) -> list[float]:
    lo, hi = math.log10(start), math.log10(stop)
    return [10 ** (lo + (hi - lo) * i / (count - 1)) for i in range(count)]


def write_svg(
    out_path: Path,
    curves: dict[str, list[float]],
    freqs: list[float],
    half: int,
    fs: int,
    y_min: int = -18,
    y_max: int = 12,
) -> None:
    width, height = 1180, 720
    ml, mr, mt, mb = 82, 210, 44, 76
    plot_w, plot_h = width - ml - mr, height - mt - mb
    x0, x1 = math.log10(20), math.log10(20000)

    def sx(freq: float) -> float:
        return ml + (math.log10(freq) - x0) / (x1 - x0) * plot_w

    def sy(db: float) -> float:
        return mt + (y_max - db) / (y_max - y_min) * plot_h

    def esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfbf8"/>',
        (
            f'<text x="{ml}" y="28" font-family="Arial, sans-serif" font-size="20" '
            f'font-weight="700" fill="#111827">CXD3778GF tone-control frequency response, '
            f"half {half} ({fs} Hz assumption)</text>"
        ),
    ]

    for freq in (20, 30, 40, 50, 60, 80, 100, 200, 300, 400, 500, 600, 800,
                 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 20000):
        x = sx(freq)
        major = freq in (20, 100, 1000, 10000, 20000)
        svg.append(
            f'<line x1="{x:.2f}" y1="{mt}" x2="{x:.2f}" y2="{mt + plot_h}" '
            f'stroke="{"#c9c9c9" if major else "#e7e2d8"}" '
            f'stroke-width="{1.2 if major else 0.7}"/>'
        )
    for db in range(y_min, y_max + 1, 3):
        y = sy(db)
        major = db == 0
        svg.append(
            f'<line x1="{ml}" y1="{y:.2f}" x2="{ml + plot_w}" y2="{y:.2f}" '
            f'stroke="{"#9ca3af" if major else "#e3dfd7"}" '
            f'stroke-width="{1.5 if major else 0.8}"/>'
        )
        svg.append(
            f'<text x="{ml - 12}" y="{y + 4:.2f}" text-anchor="end" '
            f'font-family="Arial, sans-serif" font-size="12" fill="#374151">{db}</text>'
        )
    for freq, label in ((20, "20"), (100, "100"), (1000, "1k"), (10000, "10k"), (20000, "20k")):
        svg.append(
            f'<text x="{sx(freq):.2f}" y="{mt + plot_h + 24}" text-anchor="middle" '
            f'font-family="Arial, sans-serif" font-size="13" fill="#374151">{label}</text>'
        )

    svg.extend([
        (
            f'<text x="{ml + plot_w / 2:.2f}" y="{height - 20}" text-anchor="middle" '
            'font-family="Arial, sans-serif" font-size="14" fill="#111827">'
            "Frequency (Hz, log scale)</text>"
        ),
        (
            f'<text transform="translate(24 {mt + plot_h / 2:.2f}) rotate(-90)" '
            'text-anchor="middle" font-family="Arial, sans-serif" font-size="14" '
            'fill="#111827">Magnitude (dB)</text>'
        ),
        f'<rect x="{ml}" y="{mt}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#111827" stroke-width="1"/>',
    ])

    for name, values in curves.items():
        points = []
        for freq, db in zip(freqs, values):
            points.append(f"{sx(freq):.2f},{sy(max(y_min, min(y_max, db))):.2f}")
        dash = ' stroke-dasharray="7 5"' if name == "sg" else ""
        svg.append(
            f'<polyline points="{" ".join(points)}" fill="none" '
            f'stroke="{COLORS.get(name, "#111827")}" stroke-width="2.0" '
            f'stroke-linejoin="round" stroke-linecap="round"{dash}/>'
        )

    lx, ly = ml + plot_w + 26, mt + 24
    for idx, name in enumerate(curves):
        y = ly + idx * 28
        dash = ' stroke-dasharray="7 5"' if name == "sg" else ""
        svg.append(
            f'<line x1="{lx}" y1="{y}" x2="{lx + 34}" y2="{y}" '
            f'stroke="{COLORS.get(name, "#111827")}" stroke-width="3"{dash}/>'
        )
        svg.append(
            f'<text x="{lx + 44}" y="{y + 5}" font-family="Arial, sans-serif" '
            f'font-size="13" fill="#111827">{esc(LABELS.get(name, name))}</text>'
        )
    svg.append("</svg>")
    out_path.write_text("\n".join(svg))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-dir", type=Path, help="directory containing proc_tct_<name>.bin chunks")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--chunks", nargs="*", default=list(DEFAULT_CHUNKS), help="chunk names under --dump-dir")
    parser.add_argument(
        "--chunk-file",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="extra 320-byte or 328-byte chunk/blob to plot; may be repeated",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    freqs = logspace(20, 20000, 900)
    summary_lines: list[str] = []

    chunk_paths: dict[str, Path] = {}
    if args.dump_dir:
        for name in args.chunks:
            chunk_paths[name] = args.dump_dir / f"proc_tct_{name}.bin"
    for item in args.chunk_file:
        if "=" not in item:
            raise SystemExit(f"--chunk-file must be NAME=PATH, got {item!r}")
        name, path = item.split("=", 1)
        if not name:
            raise SystemExit(f"--chunk-file has empty NAME: {item!r}")
        chunk_paths[name] = Path(path)
    if not chunk_paths:
        raise SystemExit("provide --dump-dir/--chunks or at least one --chunk-file NAME=PATH")

    key_freqs = (20, 31.5, 63, 100, 200, 500, 1000, 2000, 4000, 8000, 10000, 16000, 20000)
    for half, fs in ((0, 44100), (1, 48000)):
        curves: dict[str, list[float]] = {}
        for name, path in chunk_paths.items():
            sections = decode_sections(path, half)
            curves[name] = [response_db(sections, freq, fs) for freq in freqs]
            key_points = [
                f"{freq:g}Hz:{response_db(sections, freq, fs):.2f}dB"
                for freq in key_freqs
                if freq < fs / 2
            ]
            summary_lines.append(
                f"half={half} fs={fs} table={name} "
                f"min={min(curves[name]):.3f}dB max={max(curves[name]):.3f}dB\n"
                f"  {', '.join(key_points)}"
            )

        csv_path = args.out_dir / f"cxd3778gf_tct_response_half{half}_{fs}hz.csv"
        with csv_path.open("w", newline="") as fp:
            writer = csv.writer(fp)
            curve_names = list(curves)
            writer.writerow(["frequency_hz", *curve_names])
            for idx, freq in enumerate(freqs):
                writer.writerow([freq, *[curves[name][idx] for name in curve_names]])

        write_svg(args.out_dir / f"cxd3778gf_tct_response_half{half}_{fs}hz.svg", curves, freqs, half, fs)

    (args.out_dir / "cxd3778gf_tct_response_summary.txt").write_text("\n".join(summary_lines) + "\n")


if __name__ == "__main__":
    main()
