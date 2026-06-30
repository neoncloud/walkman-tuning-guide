#!/usr/bin/env python3
"""Fit a CXD3778GF five-biquad chunk using an IIRNet-style SOS parameterization.

This does not use IIRNet's pretrained neural network directly. Instead it adopts
the same practical idea used by IIRNet's optimization baseline: optimize a
stable second-order-section cascade in the frequency domain. Each section is
parameterized as a conjugate pole pair and conjugate zero pair inside the unit
circle, plus one global gain. The resulting free SOS cascade is less constrained
than RBJ peaking/shelf filters, but still maps directly to the CXD3778GF table.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.optimize import differential_evolution, least_squares

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

import autoeq_to_cxd3778gf_peq as peq  # noqa: E402

SECTIONS = 5
FREQS_FOR_SUMMARY = (20, 31.5, 63, 100, 200, 500, 1000, 2000, 4000, 8000, 10000, 16000, 20000)


def logspace(start: float, stop: float, count: int) -> np.ndarray:
    return np.logspace(math.log10(start), math.log10(stop), count)


def load_target(path: Path, fs_expected: float, nfft: int, freqs: np.ndarray) -> np.ndarray:
    fs, impulse = wavfile.read(path)
    if fs != int(fs_expected):
        raise SystemExit(f"{path}: expected {fs_expected:g} Hz WAV, got {fs} Hz")
    if impulse.ndim > 1:
        impulse = impulse[:, 0]
    original_dtype = impulse.dtype
    impulse = impulse.astype(np.float64)
    if np.issubdtype(original_dtype, np.integer):
        impulse /= np.iinfo(original_dtype).max
    spectrum = np.fft.rfft(impulse, nfft)
    fft_freqs = np.fft.rfftfreq(nfft, 1.0 / fs)
    mag_db = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1e-12))
    return np.interp(freqs, fft_freqs, mag_db)


def section_to_zp(section: list[float]) -> tuple[float, float, float, float]:
    b0, b1, b2, neg_a1, neg_a2 = section
    zeros = np.roots([b0, b1, b2]) if abs(b0) > 1e-12 else np.array([0.0, 0.0])
    poles = np.roots([1.0, -neg_a1, -neg_a2])
    zero = zeros[np.argmax(np.imag(zeros))] if len(zeros) else 0.0j
    pole = poles[np.argmax(np.imag(poles))] if len(poles) else 0.0j
    rz = min(0.98, max(0.0, abs(zero)))
    rp = min(0.98, max(0.0, abs(pole)))
    tz = float(np.clip(abs(np.angle(zero)), 1e-3, math.pi - 1e-3))
    tp = float(np.clip(abs(np.angle(pole)), 1e-3, math.pi - 1e-3))
    return rz, tz, rp, tp


def rbj_initial_params(peq_text: str | None) -> np.ndarray:
    params = [0.0]
    if peq_text:
        preamp, filters = peq.parse_autoeq(peq_text)
        sections = peq.identity_sections()
        for i, filt in enumerate(filters[:SECTIONS]):
            sections[i] = peq.coefficients(filt, 48000.0)
        params[0] = preamp
        for section in sections:
            params.extend(section_to_zp(section))
    else:
        centers = [70.0, 250.0, 1000.0, 4000.0, 10000.0]
        for freq in centers:
            theta = 2.0 * math.pi * freq / 48000.0
            params.extend([0.5, theta, 0.5, theta])
    return np.array(params, dtype=np.float64)


def params_to_sections(params: np.ndarray) -> tuple[float, list[list[float]]]:
    gain_db = float(params[0])
    sections = []
    offset = 1
    for _ in range(SECTIONS):
        rz, tz, rp, tp = params[offset : offset + 4]
        b0 = 1.0
        b1 = -2.0 * rz * math.cos(tz)
        b2 = rz * rz
        neg_a1 = 2.0 * rp * math.cos(tp)
        neg_a2 = -(rp * rp)
        sections.append([b0, b1, b2, neg_a1, neg_a2])
        offset += 4
    gain = 10.0 ** (gain_db / 20.0)
    sections[0][0] *= gain
    sections[0][1] *= gain
    sections[0][2] *= gain
    return gain_db, sections


def response_db(sections: list[list[float]], freqs: np.ndarray, fs: float) -> np.ndarray:
    w = 2.0 * np.pi * freqs / fs
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    h = np.ones_like(z1, dtype=np.complex128)
    for b0, b1, b2, neg_a1, neg_a2 in sections:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 - neg_a1 * z1 - neg_a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def bounds(max_pole_radius: float) -> tuple[np.ndarray, np.ndarray]:
    lower = [-24.0]
    upper = [12.0]
    for _ in range(SECTIONS):
        lower.extend([0.0, 1e-4, 0.0, 1e-4])
        upper.extend([0.999, math.pi - 1e-4, max_pole_radius, math.pi - 1e-4])
    return np.array(lower, dtype=np.float64), np.array(upper, dtype=np.float64)


def section_response_db(section: list[float], freqs: np.ndarray, fs: float) -> np.ndarray:
    b0, b1, b2, neg_a1, neg_a2 = section
    w = 2.0 * np.pi * freqs / fs
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    h = (b0 + b1 * z1 + b2 * z2) / (1.0 - neg_a1 * z1 - neg_a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def residuals(
    params: np.ndarray,
    freqs: np.ndarray,
    target_db: np.ndarray,
    fs: float,
    max_section_peak_db: float,
    section_peak_weight: float,
    radius_weight: float,
) -> np.ndarray:
    _gain_db, sections = params_to_sections(params)
    got = response_db(sections, freqs, fs)
    weights = np.ones_like(freqs)
    weights[freqs > 10000.0] *= 0.65
    weights[freqs < 35.0] *= 0.75
    out = [(got - target_db) * weights]

    if max_section_peak_db is not None:
        for section in sections:
            sec_db = section_response_db(section, freqs, fs)
            out.append(np.maximum(sec_db - max_section_peak_db, 0.0) * section_peak_weight)

    # Mild radius regularization discourages razor-thin pole-zero pairs unless
    # they really pay for themselves in the target response.
    radii = params[1::4].tolist() + params[3::4].tolist()
    out.append(radius_weight * np.asarray(radii, dtype=np.float64))
    return np.concatenate(out)


def fit(
    freqs: np.ndarray,
    target_db: np.ndarray,
    fs: float,
    starts: list[np.ndarray],
    global_search: bool,
    max_pole_radius: float,
    max_section_peak_db: float,
    section_peak_weight: float,
    radius_weight: float,
    max_nfev: int,
) -> tuple[float, np.ndarray]:
    lower, upper = bounds(max_pole_radius)
    candidates = [np.minimum(np.maximum(start, lower), upper) for start in starts]
    if global_search:
        result = differential_evolution(
            lambda p: float(
                np.mean(
                    residuals(
                        p,
                        freqs,
                        target_db,
                        fs,
                        max_section_peak_db,
                        section_peak_weight,
                        radius_weight,
                    )
                    ** 2
                )
            ),
            bounds=list(zip(lower, upper)),
            maxiter=100,
            popsize=12,
            polish=False,
            seed=3778,
            workers=1,
            updating="immediate",
            tol=1e-6,
        )
        candidates.append(result.x)

    best_cost = None
    best_params = None
    for start in candidates:
        result = least_squares(
            residuals,
            start,
            args=(freqs, target_db, fs, max_section_peak_db, section_peak_weight, radius_weight),
            bounds=(lower, upper),
            max_nfev=max_nfev,
            xtol=1e-10,
            ftol=1e-10,
            gtol=1e-10,
        )
        got = response_db(params_to_sections(result.x)[1], freqs, fs)
        cost = float(np.sqrt(np.mean((got - target_db) ** 2)))
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_params = result.x
    assert best_cost is not None and best_params is not None
    return best_cost, best_params


def encode_half(sections: list[list[float]]) -> bytes:
    words = []
    for section in sections:
        words.extend(section)
    words.extend([0.0] * (peq.HALF_WORDS - len(words)))
    return b"".join(peq.encode_q37(value) for value in words)


def render_chunk(sections: list[list[float]]) -> bytes:
    # The optimized section coefficients are in z^-1 form and independent of fs.
    # We fit at 48 kHz and use the same SOS for both halves as a first IIRNet-style
    # experiment. A later version can run independent 44.1k/48k fits.
    body = encode_half(sections) + encode_half(sections)
    if len(body) != peq.CHUNK_SIZE:
        raise RuntimeError(f"bad chunk length {len(body)}")
    return body


def write_csv(path: Path, freqs: np.ndarray, target_db: np.ndarray, fitted_db: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["frequency_hz,target_db,fitted_iir_db,error_db"]
    lines.extend(
        f"{freq:.8g},{target:.8g},{fitted:.8g},{fitted - target:.8g}"
        for freq, target, fitted in zip(freqs, target_db, fitted_db)
    )
    path.write_text("\n".join(lines) + "\n")


def write_svg(path: Path, freqs: np.ndarray, target_db: np.ndarray, fitted_db: np.ndarray) -> None:
    from fit_cxd3778gf_iir_to_wav import write_fit_svg

    write_fit_svg(path, freqs, target_db, fitted_db)


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=Path)
    parser.add_argument("chunk", type=Path)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--autoeq-peq", type=Path)
    parser.add_argument("--points", type=int, default=512)
    parser.add_argument("--fs", type=float, default=48000.0)
    parser.add_argument("--global-search", action="store_true")
    parser.add_argument("--max-pole-radius", type=float, default=0.94)
    parser.add_argument("--max-section-peak-db", type=float, default=6.0)
    parser.add_argument("--section-peak-weight", type=float, default=5.0)
    parser.add_argument("--radius-weight", type=float, default=0.01)
    parser.add_argument("--random-starts", type=int, default=6)
    parser.add_argument("--max-nfev", type=int, default=2500)
    parser.add_argument("--plot-svg", type=Path)
    parser.add_argument("--plot-csv", type=Path)
    args = parser.parse_args()

    freqs = logspace(20.0, 20000.0, args.points)
    target_db = load_target(args.wav, args.fs, 65536, freqs)
    starts = [rbj_initial_params(args.autoeq_peq.read_text() if args.autoeq_peq else None)]
    # A few deterministic broadband initializations help avoid local minima.
    rng = np.random.default_rng(3778)
    for _ in range(args.random_starts):
        start = rbj_initial_params(None)
        start[0] = float(rng.uniform(-8.0, 0.0))
        start[1::4] = rng.uniform(0.05, 0.95, SECTIONS)
        start[2::4] = np.sort(rng.uniform(1e-3, math.pi - 1e-3, SECTIONS))
        start[3::4] = rng.uniform(0.05, 0.95, SECTIONS)
        start[4::4] = np.sort(rng.uniform(1e-3, math.pi - 1e-3, SECTIONS))
        starts.append(start)

    rms_db, params = fit(
        freqs,
        target_db,
        args.fs,
        starts,
        args.global_search,
        args.max_pole_radius,
        args.max_section_peak_db,
        args.section_peak_weight,
        args.radius_weight,
        args.max_nfev,
    )
    gain_db, sections = params_to_sections(params)
    fitted_db = response_db(sections, freqs, args.fs)
    error_db = fitted_db - target_db
    stats = section_stats(sections, freqs, args.fs)
    chunk = render_chunk(sections)
    args.chunk.parent.mkdir(parents=True, exist_ok=True)
    args.chunk.write_bytes(chunk)
    if args.plot_svg:
        write_svg(args.plot_svg, freqs, target_db, fitted_db)
    if args.plot_csv:
        write_csv(args.plot_csv, freqs, target_db, fitted_db)

    metadata = {
        "method": "IIRNet-style stable pole-zero SOS least-squares fit",
        "wav": str(args.wav),
        "fs": args.fs,
        "global_gain_db": gain_db,
        "unweighted_rms_db": rms_db,
        "max_abs_error_db": float(np.max(np.abs(error_db))),
        "constraints": {
            "max_pole_radius": args.max_pole_radius,
            "max_section_peak_db": args.max_section_peak_db,
            "section_peak_weight": args.section_peak_weight,
            "radius_weight": args.radius_weight,
            "random_starts": args.random_starts,
            "max_nfev": args.max_nfev,
        },
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
    for hz in FREQS_FOR_SUMMARY:
        idx = int(np.argmin(np.abs(freqs - hz)))
        metadata["key_points"].append(
            {
                "frequency_hz": float(freqs[idx]),
                "target_db": float(target_db[idx]),
                "fitted_db": float(fitted_db[idx]),
                "error_db": float(error_db[idx]),
            }
        )
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n")

    print(f"method={metadata['method']}")
    print(f"global_gain_db={gain_db:.4f}")
    print(f"unweighted_rms={rms_db:.4f}dB max_abs={metadata['max_abs_error_db']:.4f}dB")
    for index, section in enumerate(sections, start=1):
        stat = stats[index - 1]
        print(
            f"section {index}: "
            f"b0={section[0]:+.9f} b1={section[1]:+.9f} b2={section[2]:+.9f} "
            f"neg_a1={section[3]:+.9f} neg_a2={section[4]:+.9f} "
            f"sec_peak={stat['max_db']:+.2f}dB pole_r={stat['max_pole_radius']:.4f}"
        )
    print(f"written={args.chunk}")
    print(f"metadata={args.metadata}")
    if args.plot_svg:
        print(f"plot_svg={args.plot_svg}")
    if args.plot_csv:
        print(f"plot_csv={args.plot_csv}")


if __name__ == "__main__":
    main()
