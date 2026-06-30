#!/usr/bin/env python3
"""Analyze stepped-sine recordings made from make_peq_measurement_wav.py."""

from __future__ import annotations

import argparse
import csv
import math
import wave
from pathlib import Path


def read_wav_mono(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), 'rb') as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        sr = wf.getframerate()
        if width != 2:
            raise ValueError(f'{path}: expected 16-bit PCM WAV, got sample width {width}')
        raw = wf.readframes(wf.getnframes())
    samples = []
    scale = 32768.0
    stride = channels * width
    for off in range(0, len(raw), stride):
        total = 0.0
        for ch in range(channels):
            total += int.from_bytes(raw[off + ch * width:off + (ch + 1) * width], 'little', signed=True) / scale
        samples.append(total / channels)
    return sr, samples


def sine_amplitude(samples: list[float], sr: int, freq: float, start: int, count: int) -> float:
    end = min(len(samples), start + count)
    if end <= start:
        return float('nan')
    sin_sum = 0.0
    cos_sum = 0.0
    n = end - start
    for i, sample in enumerate(samples[start:end]):
        phase = 2.0 * math.pi * freq * i / sr
        sin_sum += sample * math.sin(phase)
        cos_sum += sample * math.cos(phase)
    return 2.0 * math.sqrt(sin_sum * sin_sum + cos_sum * cos_sum) / n


def load_manifest(path: Path) -> list[dict[str, float]]:
    with path.open(newline='') as fp:
        rows = []
        for row in csv.DictReader(fp):
            rows.append({key: float(value) for key, value in row.items()})
        return rows


def analyze(path: Path, manifest: Path) -> tuple[int, dict[float, float]]:
    sr, samples = read_wav_mono(path)
    result = {}
    for row in load_manifest(manifest):
        freq = row['frequency_hz']
        start = int(row['analyze_start_sample'])
        count = int(row['analyze_sample_count'])
        result[freq] = sine_amplitude(samples, sr, freq, start, count)
    return sr, result


def db(value: float) -> float:
    return -240.0 if value <= 1e-12 else 20.0 * math.log10(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--flat', type=Path, help='recording with stock/flat table')
    parser.add_argument('--peq', type=Path, required=True, help='recording with custom PEQ table')
    parser.add_argument('--csv-out', type=Path)
    args = parser.parse_args()

    peq_sr, peq = analyze(args.peq, args.manifest)
    flat = None
    if args.flat:
        flat_sr, flat = analyze(args.flat, args.manifest)
        if flat_sr != peq_sr:
            raise ValueError(f'sample-rate mismatch: flat={flat_sr}, peq={peq_sr}')

    rows = []
    for freq in sorted(peq):
        peq_db = db(peq[freq])
        row = {'frequency_hz': freq, 'peq_dbfs': peq_db}
        if flat is not None:
            flat_db = db(flat[freq])
            row['flat_dbfs'] = flat_db
            row['delta_db'] = peq_db - flat_db
            print(f'{freq:8.1f} Hz  flat={flat_db:8.2f} dBFS  peq={peq_db:8.2f} dBFS  delta={peq_db - flat_db:7.2f} dB')
        else:
            print(f'{freq:8.1f} Hz  peq={peq_db:8.2f} dBFS')
        rows.append(row)

    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0])
        with args.csv_out.open('w', newline='') as fp:
            writer = csv.DictWriter(fp, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == '__main__':
    main()
