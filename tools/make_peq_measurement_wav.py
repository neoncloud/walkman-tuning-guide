#!/usr/bin/env python3
"""Create a stepped-sine WAV for CXD3778GF PEQ output measurement."""

from __future__ import annotations

import argparse
import csv
import math
import wave
from pathlib import Path

DEFAULT_FREQS = (31.5, 63, 100, 200, 500, 1000, 2000, 4000, 8000, 10000, 16000)


def parse_freqs(text: str) -> list[float]:
    return [float(item) for item in text.replace(',', ' ').split() if item]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('wav', type=Path)
    parser.add_argument('--manifest', type=Path, help='CSV segment manifest; defaults to <wav>.csv')
    parser.add_argument('--sample-rate', type=int, default=44100)
    parser.add_argument('--duration', type=float, default=2.0, help='seconds per tone')
    parser.add_argument('--gap', type=float, default=0.25, help='seconds of silence before each tone')
    parser.add_argument('--fade', type=float, default=0.03, help='fade-in/out seconds')
    parser.add_argument('--level-dbfs', type=float, default=-18.0)
    parser.add_argument('--freqs', default=' '.join(str(f) for f in DEFAULT_FREQS))
    args = parser.parse_args()

    freqs = parse_freqs(args.freqs)
    manifest = args.manifest or args.wav.with_suffix(args.wav.suffix + '.csv')
    amp = 10 ** (args.level_dbfs / 20.0)
    max_i16 = 32767
    sr = args.sample_rate
    tone_n = round(args.duration * sr)
    gap_n = round(args.gap * sr)
    fade_n = max(1, round(args.fade * sr))

    args.wav.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    sample_pos = 0

    with wave.open(str(args.wav), 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for idx, freq in enumerate(freqs, start=1):
            wf.writeframes(b'\x00\x00\x00\x00' * gap_n)
            sample_pos += gap_n
            start = sample_pos
            frames = bytearray()
            for n in range(tone_n):
                env = 1.0
                if n < fade_n:
                    env = n / fade_n
                elif n >= tone_n - fade_n:
                    env = max(0.0, (tone_n - n - 1) / fade_n)
                value = int(round(max_i16 * amp * env * math.sin(2.0 * math.pi * freq * n / sr)))
                value = max(-32768, min(32767, value))
                frames += value.to_bytes(2, 'little', signed=True) * 2
            wf.writeframes(frames)
            sample_pos += tone_n
            rows.append({
                'index': idx,
                'frequency_hz': freq,
                'start_sample': start,
                'sample_count': tone_n,
                'analyze_start_sample': start + fade_n,
                'analyze_sample_count': max(1, tone_n - 2 * fade_n),
            })

    with manifest.open('w', newline='') as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f'wrote {args.wav}')
    print(f'wrote {manifest}')


if __name__ == '__main__':
    main()
