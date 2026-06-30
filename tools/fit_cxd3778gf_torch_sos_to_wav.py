#!/usr/bin/env python3
"""Fit CXD3778GF biquads to a correction WAV with Torch/CUDA.

This is a practical SGD/Adam designer for the Walkman tone table. It can either
optimize four stable SOS biquads plus one dedicated pre-gain biquad, or use all
five executed CXD sections as stable SOS biquads with the global gain folded
into the first section. The loss includes:

  - dB magnitude error on a log-frequency grid
  - per-section peak penalty
  - cascade-prefix peak penalty
  - pole/zero radius regularization

The section and prefix penalties are important for fixed-point DSP hardware:
good final frequency response is not sufficient if intermediate stages have
large hidden boosts.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.io import wavfile

TOOL_DIR = Path(__file__).resolve().parent
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


def logspace_np(start: float, stop: float, count: int) -> np.ndarray:
    return np.logspace(math.log10(start), math.log10(stop), count)


def inv_sigmoid(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 1e-5, 1.0 - 1e-5)
    return np.log(value / (1.0 - value))


def rbj_initial_params(section_count: int, fs: float, autoeq_text: str | None, max_pole_radius: float):
    gain_db = -3.0
    rz = np.full(section_count, 0.45, dtype=np.float64)
    rp = np.full(section_count, 0.45, dtype=np.float64)
    tz = np.linspace(0.1, math.pi * 0.85, section_count)
    tp = tz.copy()
    if autoeq_text:
        preamp, filters = peq.parse_autoeq(autoeq_text)
        gain_db = preamp
        for index, filt in enumerate(filters[:section_count]):
            b0, b1, b2, neg_a1, neg_a2 = peq.coefficients(filt, fs)
            zeros = np.roots([b0, b1, b2]) if abs(b0) > 1e-12 else np.asarray([0.0])
            poles = np.roots([1.0, -neg_a1, -neg_a2])
            zero = zeros[np.argmax(np.imag(zeros))] if len(zeros) else 0.0j
            pole = poles[np.argmax(np.imag(poles))] if len(poles) else 0.0j
            rz[index] = min(0.98, max(0.0, abs(zero)))
            rp[index] = min(max_pole_radius * 0.98, max(0.0, abs(pole)))
            tz[index] = float(np.clip(abs(np.angle(zero)), 1e-4, math.pi - 1e-4))
            tp[index] = float(np.clip(abs(np.angle(pole)), 1e-4, math.pi - 1e-4))
    return gain_db, rz, tz, rp, tp


def initialize_population(
    starts: int,
    section_count: int,
    fs: float,
    autoeq_text: str | None,
    max_pole_radius: float,
    device: torch.device,
) -> torch.Tensor:
    rng = np.random.default_rng(3778 + int(fs))
    params = np.zeros((starts, 1 + section_count * 4), dtype=np.float64)
    gain_db, rz, tz, rp, tp = rbj_initial_params(section_count, fs, autoeq_text, max_pole_radius)
    params[0, 0] = gain_db
    base = []
    for values, scale in ((rz / 0.995, 1.0), (tz / math.pi, 1.0), (rp / max_pole_radius, 1.0), (tp / math.pi, 1.0)):
        base.append(inv_sigmoid(values))
    # Interleave rz,tz,rp,tp logits.
    for idx in range(section_count):
        params[0, 1 + idx * 4 : 1 + idx * 4 + 4] = [base[0][idx], base[1][idx], base[2][idx], base[3][idx]]
    for row in range(1, starts):
        params[row, 0] = rng.uniform(-8.0, 0.5)
        rz = rng.uniform(0.02, 0.92, section_count)
        rp = rng.uniform(0.02, max_pole_radius * 0.98, section_count)
        tz = np.sort(rng.uniform(0.01, math.pi - 0.01, section_count))
        tp = np.sort(rng.uniform(0.01, math.pi - 0.01, section_count))
        for idx in range(section_count):
            params[row, 1 + idx * 4 : 1 + idx * 4 + 4] = [
                inv_sigmoid(np.asarray(rz[idx] / 0.995)),
                inv_sigmoid(np.asarray(tz[idx] / math.pi)),
                inv_sigmoid(np.asarray(rp[idx] / max_pole_radius)),
                inv_sigmoid(np.asarray(tp[idx] / math.pi)),
            ]
    return torch.tensor(params, dtype=torch.float64, device=device)


def unpack_params(raw: torch.Tensor, section_count: int, max_pole_radius: float):
    gain_db = raw[:, 0]
    vals = raw[:, 1:].reshape(raw.shape[0], section_count, 4)
    rz = 0.995 * torch.sigmoid(vals[:, :, 0])
    tz = math.pi * torch.sigmoid(vals[:, :, 1])
    rp = max_pole_radius * torch.sigmoid(vals[:, :, 2])
    tp = math.pi * torch.sigmoid(vals[:, :, 3])
    return gain_db, rz, tz, rp, tp


def sections_from_params(raw: torch.Tensor, section_count: int, max_pole_radius: float):
    gain_db, rz, tz, rp, tp = unpack_params(raw, section_count, max_pole_radius)
    b0 = torch.ones_like(rz)
    b1 = -2.0 * rz * torch.cos(tz)
    b2 = rz * rz
    neg_a1 = 2.0 * rp * torch.cos(tp)
    neg_a2 = -(rp * rp)
    gain = torch.pow(torch.tensor(10.0, dtype=raw.dtype, device=raw.device), gain_db / 20.0)
    return gain_db, gain, b0, b1, b2, neg_a1, neg_a2, rp, rz


def response_and_safety(
    raw: torch.Tensor,
    freqs: torch.Tensor,
    fs: float,
    section_count: int,
    max_pole_radius: float,
    layout: str,
):
    gain_db, gain, b0, b1, b2, neg_a1, neg_a2, rp, rz = sections_from_params(raw, section_count, max_pole_radius)
    w = 2.0 * math.pi * freqs / fs
    z1 = torch.exp(-1j * w).unsqueeze(0)
    z2 = z1 * z1
    if layout == "pregain4":
        h = gain.to(torch.complex128).unsqueeze(1)
    else:
        h = torch.ones((raw.shape[0], freqs.shape[0]), dtype=torch.complex128, device=raw.device)
    section_peaks = []
    prefix_peaks = []
    if layout == "pregain4":
        prefix_peaks.append(20.0 * torch.log10(torch.clamp(gain.abs(), min=1e-12)))
    for idx in range(section_count):
        sec_b0 = b0[:, idx:idx + 1]
        sec_b1 = b1[:, idx:idx + 1]
        sec_b2 = b2[:, idx:idx + 1]
        if layout == "sos5" and idx == 0:
            sec_b0 = sec_b0 * gain.unsqueeze(1)
            sec_b1 = sec_b1 * gain.unsqueeze(1)
            sec_b2 = sec_b2 * gain.unsqueeze(1)
        sec = (
            sec_b0.to(torch.complex128)
            + sec_b1.to(torch.complex128) * z1
            + sec_b2.to(torch.complex128) * z2
        ) / (
            1.0
            - neg_a1[:, idx:idx + 1].to(torch.complex128) * z1
            - neg_a2[:, idx:idx + 1].to(torch.complex128) * z2
        )
        sec_db = 20.0 * torch.log10(torch.clamp(sec.abs(), min=1e-12))
        section_peaks.append(sec_db.max(dim=1).values)
        h = h * sec
        prefix_db = 20.0 * torch.log10(torch.clamp(h.abs(), min=1e-12))
        prefix_peaks.append(prefix_db.max(dim=1).values)
    total_db = 20.0 * torch.log10(torch.clamp(h.abs(), min=1e-12))
    section_peaks_t = torch.stack(section_peaks, dim=1)
    prefix_peaks_t = torch.stack(prefix_peaks, dim=1)
    return total_db.real, section_peaks_t, prefix_peaks_t, rp, rz


def optimize_half(
    target_db_np: np.ndarray,
    freqs_np: np.ndarray,
    fs: float,
    autoeq_text: str | None,
    args,
    device: torch.device,
):
    freqs = torch.tensor(freqs_np, dtype=torch.float, device=device)
    target = torch.tensor(target_db_np, dtype=torch.float, device=device).unsqueeze(0)
    raw = initialize_population(args.starts, args.sections, fs, autoeq_text, args.max_pole_radius, device)
    raw.requires_grad_(True)
    opt = torch.optim.Adam([raw], lr=args.lr)
    best = None
    best_score = None
    best_metrics = None
    weight = torch.ones_like(target)
    weight[:, freqs > 10000.0] *= 0.65
    weight[:, freqs < 35.0] *= 0.75

    for step in range(args.steps):
        got, sec_peak, prefix_peak, rp, rz = response_and_safety(
            raw, freqs, fs, args.sections, args.max_pole_radius, args.layout
        )
        err = (got - target) * weight
        mag_loss = (err * err).mean(dim=1)
        sec_pen = torch.relu(sec_peak - args.max_section_peak_db).pow(2).mean(dim=1)
        pref_pen = torch.relu(prefix_peak - args.max_prefix_peak_db).pow(2).mean(dim=1)
        radius_pen = (rp.pow(2).mean(dim=1) + 0.2 * rz.pow(2).mean(dim=1))
        loss_vec = mag_loss + args.section_peak_weight * sec_pen + args.prefix_peak_weight * pref_pen + args.radius_weight * radius_pen
        loss = loss_vec.mean()
        opt.zero_grad()
        loss.backward()
        opt.step()

        if step % args.report_every == 0 or step == args.steps - 1:
            with torch.no_grad():
                got_eval, sec_eval, pref_eval, rp_eval, rz_eval = response_and_safety(
                    raw, freqs, fs, args.sections, args.max_pole_radius, args.layout
                )
                rms = torch.sqrt(((got_eval - target) ** 2).mean(dim=1))
                max_abs = (got_eval - target).abs().max(dim=1).values
                # Prefer candidates under safety limits; otherwise take lowest penalized score.
                safe_violation = torch.relu(sec_eval.max(dim=1).values - args.max_section_peak_db) + torch.relu(pref_eval.max(dim=1).values - args.max_prefix_peak_db)
                score = rms + 10.0 * safe_violation
                idx = int(torch.argmin(score).item())
                if best_score is None or float(score[idx].item()) < best_score:
                    best_score = float(score[idx].item())
                    best = raw[idx].detach().clone()
                    best_metrics = {
                        "step": step,
                        "rms_db": float(rms[idx].item()),
                        "max_abs_error_db": float(max_abs[idx].item()),
                        "max_section_peak_db": float(sec_eval[idx].max().item()),
                        "max_prefix_peak_db": float(pref_eval[idx].max().item()),
                        "max_pole_radius": float(rp_eval[idx].max().item()),
                    }
            if args.verbose:
                print(
                    f"fs={int(fs)} step={step} rms={best_metrics['rms_db']:.4f} "
                    f"max_abs={best_metrics['max_abs_error_db']:.3f} "
                    f"sec={best_metrics['max_section_peak_db']:+.2f} "
                    f"prefix={best_metrics['max_prefix_peak_db']:+.2f} "
                    f"pole={best_metrics['max_pole_radius']:.4f}",
                    flush=True,
                )
    assert best is not None and best_metrics is not None
    return best, best_metrics


def raw_to_sections(raw: torch.Tensor, section_count: int, max_pole_radius: float, layout: str):
    raw = raw.detach().reshape(1, -1).cpu()
    gain_db, gain, b0, b1, b2, neg_a1, neg_a2, rp, rz = sections_from_params(raw, section_count, max_pole_radius)
    gain_value = float(gain[0].item())
    sections = []
    if layout == "pregain4":
        sections.append([gain_value, 0.0, 0.0, 0.0, 0.0])
    for idx in range(section_count):
        scale = gain_value if layout == "sos5" and idx == 0 else 1.0
        sections.append(
            [
                float(b0[0, idx].item()) * scale,
                float(b1[0, idx].item()) * scale,
                float(b2[0, idx].item()) * scale,
                float(neg_a1[0, idx].item()),
                float(neg_a2[0, idx].item()),
            ]
        )
    return float(gain_db[0].item()), sections


def response_np(sections: list[list[float]], freqs: np.ndarray, fs: float) -> np.ndarray:
    w = 2.0 * np.pi * freqs / fs
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    h = np.ones_like(z1, dtype=np.complex128)
    for b0, b1, b2, neg_a1, neg_a2 in sections:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 - neg_a1 * z1 - neg_a2 * z2)
    return 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))


def section_stats_np(sections: list[list[float]], freqs: np.ndarray, fs: float):
    stats = []
    prefix = np.ones_like(freqs, dtype=np.complex128)
    prefix_peaks = []
    w = 2.0 * np.pi * freqs / fs
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    for section in sections:
        b0, b1, b2, neg_a1, neg_a2 = section
        h = (b0 + b1 * z1 + b2 * z2) / (1.0 - neg_a1 * z1 - neg_a2 * z2)
        db = 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))
        prefix *= h
        prefix_db = 20.0 * np.log10(np.maximum(np.abs(prefix), 1e-12))
        poles = np.roots([1.0, -neg_a1, -neg_a2])
        zeros = np.roots([b0, b1, b2]) if abs(b0) > 1e-12 else np.asarray([])
        prefix_peaks.append(float(np.max(prefix_db)))
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


def encode_half(sections: list[list[float]]) -> bytes:
    if len(sections) != 5:
        raise ValueError(f"expected five CXD sections, got {len(sections)}")
    words = []
    for section in sections:
        words.extend(section)
    words.extend([0.0] * (peq.HALF_WORDS - len(words)))
    return b"".join(peq.encode_q37(value) for value in words)


def write_table(base: Path, chunk: bytes, output: Path) -> bytes:
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
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--chunk", type=Path, required=True)
    parser.add_argument("--plot-dir", type=Path, required=True)
    parser.add_argument("--autoeq-peq", type=Path)
    parser.add_argument("--sections", type=int, default=4)
    parser.add_argument("--layout", choices=("pregain4", "sos5"), default="pregain4")
    parser.add_argument("--starts", type=int, default=96)
    parser.add_argument("--steps", type=int, default=2500)
    parser.add_argument("--lr", type=float, default=0.035)
    parser.add_argument("--points", type=int, default=768)
    parser.add_argument("--max-pole-radius", type=float, default=0.92)
    parser.add_argument("--max-section-peak-db", type=float, default=8.0)
    parser.add_argument("--max-prefix-peak-db", type=float, default=4.0)
    parser.add_argument("--section-peak-weight", type=float, default=0.45)
    parser.add_argument("--prefix-peak-weight", type=float, default=0.9)
    parser.add_argument("--radius-weight", type=float, default=0.01)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--report-every", type=int, default=250)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    device = torch.device(args.device if args.device == "cpu" or torch.cuda.is_available() else "cpu")
    if args.layout == "pregain4" and args.sections != 4:
        raise SystemExit("--layout pregain4 expects --sections 4")
    if args.layout == "sos5" and args.sections != 5:
        raise SystemExit("--layout sos5 expects --sections 5")
    autoeq_text = args.autoeq_peq.read_text() if args.autoeq_peq else None
    _wav_fs, target_freqs, target_mag_db = load_target_wav(args.wav)
    eval_freqs = logspace_np(20.0, 20000.0, args.points)
    target_eval = np.interp(eval_freqs, target_freqs, target_mag_db)

    halves = {}
    half_blobs = []
    for fs in (44100.0, 48000.0):
        best_raw, metrics = optimize_half(target_eval, eval_freqs, fs, autoeq_text, args, device)
        gain_db, sections = raw_to_sections(best_raw, args.sections, args.max_pole_radius, args.layout)
        fitted = response_np(sections, eval_freqs, fs)
        err = fitted - target_eval
        stats = section_stats_np(sections, eval_freqs, fs)
        fs_key = str(int(fs))
        args.plot_dir.mkdir(parents=True, exist_ok=True)
        write_fit_svg(args.plot_dir / f"torch-sgd-4sos-pregain-{fs_key}hz.svg", eval_freqs, target_eval, fitted)
        write_fit_csv(args.plot_dir / f"torch-sgd-4sos-pregain-{fs_key}hz.csv", eval_freqs, target_eval, fitted)
        half_blobs.append(encode_half(sections))
        halves[fs_key] = {
            "fs": fs,
            "device": str(device),
            "gain_db": gain_db,
            "rms_db": float(np.sqrt(np.mean(err ** 2))),
            "max_abs_error_db": float(np.max(np.abs(err))),
            "max_section_peak_db": float(max(item["max_db"] for item in stats)),
            "max_prefix_peak_db": float(max(item["prefix_max_db"] for item in stats)),
            "max_pole_radius": float(max(item["max_pole_radius"] for item in stats)),
            "optimizer_metrics": metrics,
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
                    "fitted_db": float(fitted[idx]),
                    "error_db": float(err[idx]),
                }
            )
        print(
            f"fs={fs_key} gain={gain_db:+.3f}dB rms={halves[fs_key]['rms_db']:.3f}dB "
            f"max_abs={halves[fs_key]['max_abs_error_db']:.3f}dB "
            f"sec={halves[fs_key]['max_section_peak_db']:+.2f}dB "
            f"prefix={halves[fs_key]['max_prefix_peak_db']:+.2f}dB "
            f"pole={halves[fs_key]['max_pole_radius']:.4f}",
            flush=True,
        )

    chunk = b"".join(half_blobs)
    args.chunk.parent.mkdir(parents=True, exist_ok=True)
    args.chunk.write_bytes(chunk)
    args.chunk.with_suffix(".tbl").write_bytes(chunk + struct.pack("<II", *tct.checksum(chunk)))
    new_body = write_table(args.base_table, chunk, args.output_table)

    metadata = {
        "method": "Torch Adam CUDA stable pole-zero SOS fit for CXD3778GF",
        "wav": str(args.wav),
        "base_table": str(args.base_table),
        "output_table": str(args.output_table),
        "chunk": str(args.chunk),
        "body_md5": __import__("hashlib").md5(new_body).hexdigest(),
        "chunk_md5": __import__("hashlib").md5(chunk).hexdigest(),
        "constraints": {
            "sections": args.sections,
            "layout": args.layout,
            "starts": args.starts,
            "steps": args.steps,
            "lr": args.lr,
            "max_pole_radius": args.max_pole_radius,
            "max_section_peak_db": args.max_section_peak_db,
            "max_prefix_peak_db": args.max_prefix_peak_db,
            "section_peak_weight": args.section_peak_weight,
            "prefix_peak_weight": args.prefix_peak_weight,
            "radius_weight": args.radius_weight,
        },
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
