#!/usr/bin/env python3
"""Generate a CXD3778GF table from IIRNet order-8 output.

IIRNet order 8 yields four SOS/biquad sections. The CXD3778GF tone table has
room for five executed biquads, so this tool moves IIRNet's first-section gain
into a dedicated pre-gain biquad and stores the four normalized IIRNet sections
after it:

    section 0: pre-gain identity biquad
    section 1..4: IIRNet order-8 SOS
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent
sys.path.insert(0, str(TOOL_DIR))

import autoeq_to_cxd3778gf_peq as peq  # noqa: E402
import cxd3778gf_tct_tool as tct  # noqa: E402
from fit_cxd3778gf_iir_to_wav import write_fit_csv, write_fit_svg  # noqa: E402
from fit_cxd3778gf_sos_iirnet_style_to_wav import section_response_db  # noqa: E402


def load_wav_response(path: Path, nfft: int = 65536):
    fs, impulse = wavfile.read(path)
    if impulse.ndim > 1:
        impulse = impulse[:, 0]
    original_dtype = impulse.dtype
    impulse = impulse.astype(np.float64)
    if np.issubdtype(original_dtype, np.integer):
        impulse /= np.iinfo(original_dtype).max
    spectrum = np.fft.rfft(impulse, nfft)
    freqs = np.fft.rfftfreq(nfft, 1.0 / fs)
    mag_db = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1e-12))
    return fs, freqs, mag_db


def iirnet_target(freqs_fft: np.ndarray, mag_db: np.ndarray, fs_out: float, points: int) -> np.ndarray:
    # IIRNet's sosfreqz/loss uses linear frequencies from 0 to Nyquist, endpoint
    # excluded. Match that grid so the input magnitude specification lines up.
    freqs = np.linspace(0.0, fs_out / 2.0, points, endpoint=False)
    return np.interp(freqs, freqs_fft, mag_db)


def sos_to_cxd_sections(sos: np.ndarray) -> list[list[float]]:
    if sos.shape != (4, 6):
        raise ValueError(f"expected IIRNet order-8 SOS shape (4, 6), got {sos.shape}")
    sos = sos.astype(np.float64).copy()
    if not np.allclose(sos[:, 3], 1.0, atol=1e-6):
        sos /= sos[:, 3:4]

    pre_gain = float(sos[0, 0])
    if pre_gain <= 0:
        raise ValueError(f"unexpected non-positive IIRNet gain {pre_gain}")
    sos[0, :3] /= pre_gain

    sections: list[list[float]] = [[pre_gain, 0.0, 0.0, 0.0, 0.0]]
    for row in sos:
        b0, b1, b2, _a0, a1, a2 = [float(v) for v in row]
        sections.append([b0, b1, b2, -a1, -a2])
    return sections


def response_db(sections: list[list[float]], freqs: np.ndarray, fs: float) -> np.ndarray:
    w = 2.0 * np.pi * freqs / fs
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    h = np.ones_like(z1, dtype=np.complex128)
    for b0, b1, b2, neg_a1, neg_a2 in sections:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 - neg_a1 * z1 - neg_a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def section_stats(sections: list[list[float]], freqs: np.ndarray, fs: float) -> list[dict[str, float]]:
    stats = []
    for section in sections:
        b0, b1, b2, neg_a1, neg_a2 = section
        poles = np.roots([1.0, -neg_a1, -neg_a2])
        zeros = np.roots([b0, b1, b2]) if abs(b0) > 1e-12 else np.asarray([])
        sec_db = section_response_db(section, freqs, fs)
        stats.append(
            {
                "max_db": float(np.max(sec_db)),
                "min_db": float(np.min(sec_db)),
                "max_pole_radius": float(np.max(np.abs(poles))) if len(poles) else 0.0,
                "max_zero_radius": float(np.max(np.abs(zeros))) if len(zeros) else 0.0,
            }
        )
    return stats


def encode_half(sections: list[list[float]]) -> bytes:
    words = []
    for section in sections:
        words.extend(section)
    words.extend([0.0] * (peq.HALF_WORDS - len(words)))
    if len(words) != peq.HALF_WORDS:
        raise ValueError(f"bad word count {len(words)}")
    return b"".join(peq.encode_q37(value) for value in words)


def build_full_table(base_table: Path, chunk: bytes, output: Path) -> bytes:
    body, _ = tct.read_table(base_table)
    chunks = [body[i * tct.CHUNK_SIZE:(i + 1) * tct.CHUNK_SIZE] for i in range(len(tct.TABLE_NAMES))]
    for name in ("ng", "sg"):
        chunks[tct.TABLE_NAMES.index(name)] = chunk
    new_body = b"".join(chunks)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(new_body + struct.pack("<II", *tct.checksum(new_body)))
    return new_body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=Path)
    parser.add_argument("output_table", type=Path)
    parser.add_argument("--base-table", type=Path, required=True)
    parser.add_argument("--iirnet-root", type=Path, default=REPO_ROOT / "external/IIRNet")
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--chunk", type=Path, required=True)
    parser.add_argument("--plot-dir", type=Path, required=True)
    parser.add_argument("--points", type=int, default=512)
    args = parser.parse_args()

    sys.path.insert(0, str(args.iirnet_root))
    cwd = Path.cwd()
    os.chdir(args.iirnet_root)
    from iirnet.designer import Designer  # noqa: WPS433

    designer = Designer()
    os.chdir(cwd)

    _wav_fs, freqs_fft, mag_db = load_wav_response(args.wav)
    halves: dict[str, dict] = {}
    half_blobs = []
    for fs_out in (44100.0, 48000.0):
        target = iirnet_target(freqs_fft, mag_db, fs_out, args.points)
        sos = designer(8, target.tolist(), mode="linear", output="sos").detach().cpu().numpy()
        sections = sos_to_cxd_sections(sos)
        half_blobs.append(encode_half(sections))

        eval_freqs = np.logspace(np.log10(20.0), np.log10(20000.0), 512)
        target_eval = np.interp(eval_freqs, freqs_fft, mag_db)
        fitted_eval = response_db(sections, eval_freqs, fs_out)
        error = fitted_eval - target_eval
        stats = section_stats(sections, eval_freqs, fs_out)

        fs_key = str(int(fs_out))
        args.plot_dir.mkdir(parents=True, exist_ok=True)
        write_fit_svg(args.plot_dir / f"iirnet8-pregain-{fs_key}hz.svg", eval_freqs, target_eval, fitted_eval)
        write_fit_csv(args.plot_dir / f"iirnet8-pregain-{fs_key}hz.csv", eval_freqs, target_eval, fitted_eval)
        halves[fs_key] = {
            "fs": fs_out,
            "rms_db": float(np.sqrt(np.mean(error ** 2))),
            "max_abs_error_db": float(np.max(np.abs(error))),
            "max_section_peak_db": float(max(item["max_db"] for item in stats)),
            "max_pole_radius": float(max(item["max_pole_radius"] for item in stats)),
            "raw_iirnet_sos": sos.tolist(),
            "sections": [
                {
                    "b0": float(section[0]),
                    "b1": float(section[1]),
                    "b2": float(section[2]),
                    "neg_a1": float(section[3]),
                    "neg_a2": float(section[4]),
                    **stats[index],
                }
                for index, section in enumerate(sections)
            ],
        }

    chunk = b"".join(half_blobs)
    args.chunk.parent.mkdir(parents=True, exist_ok=True)
    args.chunk.write_bytes(chunk)
    args.chunk.with_suffix(".tbl").write_bytes(chunk + struct.pack("<II", *tct.checksum(chunk)))
    new_body = build_full_table(args.base_table, chunk, args.output_table)

    metadata = {
        "method": "IIRNet Designer order=8, first SOS gain moved to dedicated CXD pre-gain biquad",
        "wav": str(args.wav),
        "base_table": str(args.base_table),
        "output_table": str(args.output_table),
        "chunk": str(args.chunk),
        "body_md5": __import__("hashlib").md5(new_body).hexdigest(),
        "chunk_md5": __import__("hashlib").md5(chunk).hexdigest(),
        "halves": halves,
    }
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n")

    print(metadata["method"])
    print(f"chunk_md5={metadata['chunk_md5']}")
    print(f"body_md5={metadata['body_md5']}")
    for fs_key, item in halves.items():
        print(
            f"fs={fs_key} rms={item['rms_db']:.3f}dB "
            f"max_abs={item['max_abs_error_db']:.3f}dB "
            f"max_sec_peak={item['max_section_peak_db']:+.2f}dB "
            f"max_pole_r={item['max_pole_radius']:.4f}"
        )
    print(f"output_table={args.output_table}")
    print(f"metadata={args.metadata}")


if __name__ == "__main__":
    main()
