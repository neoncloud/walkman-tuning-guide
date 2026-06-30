#!/usr/bin/env python3
"""Generate a CXD3778GF table with modified Yule-Walker IIR design."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
import scipy.signal as signal
from scipy.io import wavfile

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent
sys.path.insert(0, str(TOOL_DIR))

import autoeq_to_cxd3778gf_peq as peq  # noqa: E402
import cxd3778gf_tct_tool as tct  # noqa: E402
from fit_cxd3778gf_iir_to_wav import write_fit_csv, write_fit_svg  # noqa: E402


KEY_FREQS = (20, 31.5, 63, 100, 200, 500, 1000, 2000, 4000, 8000, 10000, 16000, 20000)


def load_target_wav(path: Path, nfft: int = 65536):
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


def logspace(start: float, stop: float, count: int) -> np.ndarray:
    return np.logspace(math.log10(start), math.log10(stop), count)


def sos_response_db(sos: np.ndarray, freqs: np.ndarray, fs: float) -> np.ndarray:
    _, h = signal.sosfreqz(sos, worN=freqs, fs=fs)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def section_response_db(row: np.ndarray, freqs: np.ndarray, fs: float) -> np.ndarray:
    return sos_response_db(row.reshape(1, 6), freqs, fs)


def normalize_sos(sos: np.ndarray) -> np.ndarray:
    out = np.asarray(sos, dtype=np.float64).copy()
    out /= out[:, 3:4]
    return out


def peak_scale_sos(sos: np.ndarray, freqs: np.ndarray, fs: float) -> np.ndarray:
    out = normalize_sos(sos)
    for idx in range(len(out) - 1):
        peak_db = float(np.max(section_response_db(out[idx], freqs, fs)))
        peak = 10.0 ** (peak_db / 20.0)
        if peak > 1.0:
            out[idx, :3] /= peak
            out[idx + 1, :3] *= peak
    return out


def coefficient_limit_scale_sos(sos: np.ndarray, coeff_limit: float = 3.75) -> np.ndarray:
    """Move numerator gain backward until every encoded coefficient fits Q37.

    Multiplying one section numerator by c and a neighboring section numerator
    by 1/c leaves the total cascade unchanged. We use this to avoid coefficients
    outside the CXD3778GF signed 40-bit Q37 range.
    """
    out = normalize_sos(sos)
    for _ in range(8):
        changed = False
        for idx in range(len(out) - 1, 0, -1):
            peak = float(np.max(np.abs(out[idx, :3])))
            if peak > coeff_limit:
                factor = peak / coeff_limit
                out[idx, :3] /= factor
                out[idx - 1, :3] *= factor
                changed = True
        if not changed:
            break
    return out


def section_stats(sos: np.ndarray, freqs: np.ndarray, fs: float):
    stats = []
    prefix = np.ones_like(freqs, dtype=np.complex128)
    w = 2.0 * np.pi * freqs / fs
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    for row in sos:
        b0, b1, b2, a0, a1, a2 = row
        h = (b0 + b1 * z1 + b2 * z2) / (a0 + a1 * z1 + a2 * z2)
        db = 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))
        prefix *= h
        prefix_db = 20.0 * np.log10(np.maximum(np.abs(prefix), 1e-12))
        poles = np.roots([a0, a1, a2])
        zeros = np.roots([b0, b1, b2]) if abs(b0) > 1e-12 else np.asarray([])
        stats.append(
            {
                "max_db": float(np.max(db)),
                "min_db": float(np.min(db)),
                "prefix_max_db": float(np.max(prefix_db)),
                "max_pole_radius": float(np.max(np.abs(poles))) if len(poles) else 0.0,
                "max_zero_radius": float(np.max(np.abs(zeros))) if len(zeros) else 0.0,
            }
        )
    return stats


def choose_safe_order_and_scale(sos: np.ndarray, freqs: np.ndarray, fs: float):
    best = None
    best_score = None
    for perm in itertools.permutations(range(len(sos))):
        candidate = peak_scale_sos(sos[list(perm)], freqs, fs)
        candidate = coefficient_limit_scale_sos(candidate)
        stats = section_stats(candidate, freqs, fs)
        max_section = max(item["max_db"] for item in stats)
        max_prefix = max(item["prefix_max_db"] for item in stats)
        max_pole = max(item["max_pole_radius"] for item in stats)
        max_coeff = float(np.max(np.abs(candidate[:, [0, 1, 2, 4, 5]])))
        # Final response is invariant to section order/scaling; optimize internal safety.
        score = (
            max(0.0, max_section - 12.0) * 2.0
            + max(0.0, max_prefix - 4.0) * 5.0
            + max(0.0, max_coeff - 3.75) * 100.0
            + max_pole
        )
        if best_score is None or score < best_score:
            best_score = score
            best = candidate
    assert best is not None
    return best


def sos_to_cxd_sections(sos: np.ndarray):
    sections = []
    for b0, b1, b2, a0, a1, a2 in normalize_sos(sos):
        sections.append([float(b0), float(b1), float(b2), float(-a1), float(-a2)])
    return sections


def encode_half(sections: list[list[float]]) -> bytes:
    if len(sections) != 5:
        raise ValueError(f"expected five sections, got {len(sections)}")
    words = []
    for section in sections:
        words.extend(section)
    words.extend([0.0] * (peq.HALF_WORDS - len(words)))
    return b"".join(peq.encode_q37(value) for value in words)


def build_table(base: Path, chunk: bytes, output: Path) -> bytes:
    body, _ = tct.read_table(base)
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
    parser.add_argument("--order", type=int, default=10)
    parser.add_argument("--points", type=int, default=512)
    parser.add_argument("--eval-points", type=int, default=768)
    args = parser.parse_args()

    sys.path.insert(0, str(args.iirnet_root))
    from iirnet.baselines.yw import yulewalk  # noqa: WPS433

    _wav_fs, target_freqs, target_db = load_target_wav(args.wav)
    halves = {}
    half_blobs = []
    for fs in (44100.0, 48000.0):
        design_norm = np.linspace(0.0, 1.0, args.points)
        design_freqs = design_norm * fs / 2.0
        design_target_db = np.interp(design_freqs, target_freqs, target_db)
        design_target_linear = 10.0 ** (design_target_db / 20.0)
        b, a = yulewalk(args.order, design_norm, design_target_linear, npt=args.points)
        sos = normalize_sos(signal.tf2sos(np.ravel(b), np.ravel(a)))

        eval_freqs = logspace(20.0, 20000.0, args.eval_points)
        target_eval = np.interp(eval_freqs, target_freqs, target_db)
        sos = choose_safe_order_and_scale(sos, eval_freqs, fs)
        fitted_eval = sos_response_db(sos, eval_freqs, fs)
        error = fitted_eval - target_eval
        stats = section_stats(sos, eval_freqs, fs)
        sections = sos_to_cxd_sections(sos)
        half_blobs.append(encode_half(sections))

        fs_key = str(int(fs))
        args.plot_dir.mkdir(parents=True, exist_ok=True)
        write_fit_svg(args.plot_dir / f"yulewalk-order{args.order}-{fs_key}hz.svg", eval_freqs, target_eval, fitted_eval)
        write_fit_csv(args.plot_dir / f"yulewalk-order{args.order}-{fs_key}hz.csv", eval_freqs, target_eval, fitted_eval)
        halves[fs_key] = {
            "fs": fs,
            "order": args.order,
            "rms_db": float(np.sqrt(np.mean(error ** 2))),
            "max_abs_error_db": float(np.max(np.abs(error))),
            "max_section_peak_db": float(max(item["max_db"] for item in stats)),
            "max_prefix_peak_db": float(max(item["prefix_max_db"] for item in stats)),
            "max_pole_radius": float(max(item["max_pole_radius"] for item in stats)),
            "sos": sos.tolist(),
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
            "key_points": [],
        }
        for hz in KEY_FREQS:
            idx = int(np.argmin(np.abs(eval_freqs - hz)))
            halves[fs_key]["key_points"].append(
                {
                    "frequency_hz": float(eval_freqs[idx]),
                    "target_db": float(target_eval[idx]),
                    "fitted_db": float(fitted_eval[idx]),
                    "error_db": float(error[idx]),
                }
            )
        print(
            f"fs={fs_key} rms={halves[fs_key]['rms_db']:.3f}dB "
            f"max_abs={halves[fs_key]['max_abs_error_db']:.3f}dB "
            f"sec={halves[fs_key]['max_section_peak_db']:+.2f}dB "
            f"prefix={halves[fs_key]['max_prefix_peak_db']:+.2f}dB "
            f"pole={halves[fs_key]['max_pole_radius']:.4f}"
        )

    chunk = b"".join(half_blobs)
    args.chunk.parent.mkdir(parents=True, exist_ok=True)
    args.chunk.write_bytes(chunk)
    args.chunk.with_suffix(".tbl").write_bytes(chunk + struct.pack("<II", *tct.checksum(chunk)))
    new_body = build_table(args.base_table, chunk, args.output_table)
    metadata = {
        "method": "Modified Yule-Walker order-10 IIR, converted to five CXD SOS sections",
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
    print(f"chunk_md5={metadata['chunk_md5']}")
    print(f"body_md5={metadata['body_md5']}")
    print(f"output_table={args.output_table}")
    print(f"metadata={args.metadata}")


if __name__ == "__main__":
    main()
