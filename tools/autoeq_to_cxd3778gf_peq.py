#!/usr/bin/env python3
"""Generate an experimental CXD3778GF tone-RAM PEQ blob from AutoEq-style filters.

The CXD3778GF tone RAM chunk used by tc_*.tbl is 320 bytes:
  - two 160-byte halves for the 44.1k-family and 48k-family coefficient sets
  - hardware measurements show fixed family clocks near 176.4 and 192 kHz;
    these are 4x only at the 44.1 and 48 kHz base input rates
  - each half has 32 signed 40-bit big-endian Q37 words
  - words 0..24 are interpreted as five biquad sections of
    b0, b1, b2, -a1, -a2
  - remaining words are zero

The output defaults to 320-byte body + 8-byte Sony checksum, suitable for the
prototype /proc/icx_audio_cxd3778gf_data/peq node.
"""

import argparse
import itertools
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

Q = 37
SCALE = 1 << Q
WORD_BITS = 40
WORD_MIN = -(1 << (WORD_BITS - 1))
WORD_MAX = (1 << (WORD_BITS - 1)) - 1
SECTIONS = 5
HALF_WORDS = 32
HALF_SIZE = HALF_WORDS * 5
CHUNK_SIZE = HALF_SIZE * 2
CHECKSUM_SIZE = 8

# ZX300A USB DAC 八档回环实测：44.1 kHz 家族固定在约 176.4 kHz，48 kHz
# 家族固定在约 192 kHz。它们只在基础档分别等于输入采样率的 4 倍；在更高
# 输入档位下依次是 2 倍、1 倍和 0.5 倍。CLI 仍允许覆盖，便于验证其他机型。
AUDIO_FS_441 = 44100.0
AUDIO_FS_48 = 48000.0
DEFAULT_TONE_FS_441 = 176400.0
DEFAULT_TONE_FS_48 = 192000.0


@dataclass
class Filter:
    kind: str
    freq: float
    gain: float
    q: float
    number: int = 0


def checksum(body: bytes):
    s = sum(body) & 0xFFFFFFFF
    x = 0
    for i, value in enumerate(body):
        x ^= (value << ((i % 4) * 8)) & 0xFFFFFFFF
    return s, x


def encode_q37(value: float) -> bytes:
    raw = int(round(value * SCALE))
    if raw < WORD_MIN or raw > WORD_MAX:
        raise ValueError(f"coefficient {value} exceeds signed Q37 40-bit range")
    if raw < 0:
        raw += 1 << WORD_BITS
    return raw.to_bytes(5, "big")


def decode_q37(word: bytes) -> float:
    raw = int.from_bytes(word, "big")
    if raw & (1 << (WORD_BITS - 1)):
        raw -= 1 << WORD_BITS
    return raw / SCALE


def identity_sections():
    return [[1.0, 0.0, 0.0, 0.0, 0.0] for _ in range(SECTIONS)]


def coefficients_fit_q37(sections: Iterable[Iterable[float]]) -> bool:
    """检查浮点系数四舍五入到 Q37 后是否都能放进 signed 40-bit。"""
    for section in sections:
        for value in section:
            raw = int(round(value * SCALE))
            if raw < WORD_MIN or raw > WORD_MAX:
                return False
    return True


def distribute_preamp_for_q37(sections: List[List[float]], preamp_db: float) -> List[List[float]]:
    """在各段 numerator 之间等价分配 preamp，避免单个 Q37 系数溢出。

    级联中每段 numerator 的常数缩放最终只以乘积出现。因此，只要所有缩放
    因子的乘积仍等于原始 preamp gain，总频响就不变。通常仍沿用“全部折入
    第一段”的简单表示；只有它无法编码时，才在 log-gain 域做受限均匀分配。
    """
    gain = 10 ** (preamp_db / 20.0)
    legacy = [list(section) for section in sections]
    for index in range(3):
        legacy[0][index] *= gain
    if coefficients_fit_q37(legacy):
        return legacy

    # denominator 不能通过段间增益重分配改变；若它自身溢出只能拒绝。
    for section_index, section in enumerate(sections):
        if not coefficients_fit_q37([[0.0, 0.0, 0.0, section[3], section[4]]]):
            raise ValueError(
                f"section {section_index + 1} denominator exceeds signed Q37 range"
            )

    # 给每段计算 numerator 可接受的最大正缩放。留一个 LSB 余量，避免浮点
    # 边界在 round() 时跨出 WORD_MAX。
    safe_max = (WORD_MAX - 1) / SCALE
    caps = []
    for section in sections:
        numerator_max = max(abs(value) for value in section[:3])
        caps.append(safe_max / numerator_max)

    max_product = math.prod(caps)
    if gain > max_product:
        extra_attenuation_db = 20.0 * math.log10(gain / max_product)
        raise ValueError(
            "preamp is insufficient for the signed Q37 coefficient range; "
            f"reduce preamp by at least {extra_attenuation_db:.3f} dB"
        )

    # 求一个共同 log-scale；达到某段上限后将它钳住，其余段继续共同承担增益。
    target_log = math.log(gain)
    cap_logs = [math.log(cap) for cap in caps]
    low = min(target_log - 100.0, min(cap_logs) - 100.0)
    high = max(max(cap_logs), target_log) + 100.0
    for _ in range(200):
        middle = (low + high) / 2.0
        total = sum(min(middle, cap_log) for cap_log in cap_logs)
        if total < target_log:
            low = middle
        else:
            high = middle
    common_log = (low + high) / 2.0
    scales = [math.exp(min(common_log, cap_log)) for cap_log in cap_logs]

    distributed = [list(section) for section in sections]
    for section, scale in zip(distributed, scales):
        for index in range(3):
            section[index] *= scale
    if not coefficients_fit_q37(distributed):
        raise ValueError("internal error: distributed preamp still exceeds signed Q37 range")
    return distributed


def rbj_peaking(f: Filter, fs: float):
    a = 10 ** (f.gain / 40.0)
    w0 = 2.0 * math.pi * f.freq / fs
    alpha = math.sin(w0) / (2.0 * f.q)
    cosw = math.cos(w0)
    b0 = 1.0 + alpha * a
    b1 = -2.0 * cosw
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cosw
    a2 = 1.0 - alpha / a
    return [b0 / a0, b1 / a0, b2 / a0, -(a1 / a0), -(a2 / a0)]


def rbj_lowshelf(f: Filter, fs: float):
    a = 10 ** (f.gain / 40.0)
    w0 = 2.0 * math.pi * f.freq / fs
    cosw = math.cos(w0)
    sinw = math.sin(w0)
    # Interpret Q as shelf slope S when present; S=1 is RBJ's gentle default.
    s = max(f.q, 1e-6)
    alpha = sinw / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / s - 1.0) + 2.0)
    beta = 2.0 * math.sqrt(a) * alpha
    b0 = a * ((a + 1) - (a - 1) * cosw + beta)
    b1 = 2 * a * ((a - 1) - (a + 1) * cosw)
    b2 = a * ((a + 1) - (a - 1) * cosw - beta)
    a0 = (a + 1) + (a - 1) * cosw + beta
    a1 = -2 * ((a - 1) + (a + 1) * cosw)
    a2 = (a + 1) + (a - 1) * cosw - beta
    return [b0 / a0, b1 / a0, b2 / a0, -(a1 / a0), -(a2 / a0)]


def rbj_highshelf(f: Filter, fs: float):
    a = 10 ** (f.gain / 40.0)
    w0 = 2.0 * math.pi * f.freq / fs
    cosw = math.cos(w0)
    sinw = math.sin(w0)
    s = max(f.q, 1e-6)
    alpha = sinw / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / s - 1.0) + 2.0)
    beta = 2.0 * math.sqrt(a) * alpha
    b0 = a * ((a + 1) + (a - 1) * cosw + beta)
    b1 = -2 * a * ((a - 1) + (a + 1) * cosw)
    b2 = a * ((a + 1) + (a - 1) * cosw - beta)
    a0 = (a + 1) - (a - 1) * cosw + beta
    a1 = 2 * ((a - 1) - (a + 1) * cosw)
    a2 = (a + 1) - (a - 1) * cosw - beta
    return [b0 / a0, b1 / a0, b2 / a0, -(a1 / a0), -(a2 / a0)]


def coefficients(f: Filter, fs: float):
    kind = f.kind.upper()
    if kind in ("PK", "PEQ", "PEAK", "PEAKING"):
        return rbj_peaking(f, fs)
    if kind in ("LS", "LSC", "LOW_SHELF", "LOWSHELF"):
        return rbj_lowshelf(f, fs)
    if kind in ("HS", "HSC", "HIGH_SHELF", "HIGHSHELF"):
        return rbj_highshelf(f, fs)
    raise ValueError(f"unsupported filter type {f.kind!r}; supported: PK, LS/LSC, HS/HSC")


def parse_autoeq(text: str):
    filters: List[Filter] = []
    preamp = 0.0
    preamp_re = re.compile(r"^\s*Preamp:\s*([-+0-9.]+)\s*dB", re.I)
    # Example: Filter 1: ON PK Fc 105 Hz Gain -5.2 dB Q 0.70
    filt_re = re.compile(
        r"^\s*Filter\s+(?P<number>\d+):\s+ON\s+(?P<kind>\S+)\s+Fc\s+(?P<freq>[-+0-9.]+)\s+Hz\s+Gain\s+(?P<gain>[-+0-9.]+)\s+dB\s+Q\s+(?P<q>[-+0-9.]+)",
        re.I,
    )
    for line in text.splitlines():
        m = preamp_re.search(line)
        if m:
            preamp = float(m.group(1))
            continue
        m = filt_re.search(line)
        if m:
            filters.append(
                Filter(
                    m.group("kind"),
                    float(m.group("freq")),
                    float(m.group("gain")),
                    float(m.group("q")),
                    int(m.group("number")),
                )
            )
    return preamp, filters


def filter_score(f: Filter, strategy: str) -> float:
    kind = f.kind.upper()
    gain = abs(f.gain)
    if strategy == "largest":
        return gain
    if strategy == "wide":
        if kind in ("LS", "LSC", "LOW_SHELF", "LOWSHELF", "HS", "HSC", "HIGH_SHELF", "HIGHSHELF"):
            return gain * 1.5
        return gain / math.sqrt(max(f.q, 0.05))
    raise ValueError(f"unknown filter strategy {strategy!r}")


def logspace(start: float, stop: float, count: int) -> List[float]:
    lo = math.log10(start)
    hi = math.log10(stop)
    return [10 ** (lo + (hi - lo) * i / (count - 1)) for i in range(count)]


def response_db_for_filters(filters: Iterable[Filter], freqs: Iterable[float], fs: float) -> List[float]:
    sections = [coefficients(f, fs) for f in filters]
    out = []
    for freq in freqs:
        z1_real = math.cos(-2.0 * math.pi * freq / fs)
        z1_imag = math.sin(-2.0 * math.pi * freq / fs)
        z1 = complex(z1_real, z1_imag)
        z2 = z1 * z1
        h = 1.0 + 0.0j
        for b0, b1, b2, neg_a1, neg_a2 in sections:
            h *= (b0 + b1 * z1 + b2 * z2) / (1.0 - neg_a1 * z1 - neg_a2 * z2)
        mag = abs(h)
        out.append(-240.0 if mag <= 1e-12 else 20.0 * math.log10(mag))
    return out


def rms_error_db(candidate: List[Filter], target_db: List[float], freqs: List[float], fs: float) -> float:
    candidate_db = response_db_for_filters(candidate, freqs, fs)
    total = 0.0
    for got, want in zip(candidate_db, target_db):
        diff = got - want
        total += diff * diff
    return math.sqrt(total / len(target_db))


def limit_preamp_for_headroom(
    filters: List[Filter],
    requested_preamp_db: float,
    fs441: float,
    fs48: float,
    filter_strategy: str,
    max_sections: int,
    headroom_db: float = 0.0,
) -> float:
    """按实际 tone-DSP 时钟重新计算 AutoEq preamp，防止可听频段 boost 削波。

    AutoEq 文件里的 preamp 通常按 44.1/48 kHz 软件 EQ 计算。tone IIR 改按
    176.4/192 kHz 设计后，高频双线性扭曲不同，原 preamp 不一定仍覆盖所有
    filter 的叠加峰值。这里只增加必要的全局衰减，不改变滤波器相对频响。
    """
    if headroom_db < 0.0:
        raise ValueError(f"headroom_db must be non-negative, got {headroom_db}")
    selected, _ignored = select_filters(filters, filter_strategy, max_sections)
    freqs = logspace(20.0, 20000.0, 8192)
    max_filter_db = max(
        max(response_db_for_filters(selected, freqs, fs441)),
        max(response_db_for_filters(selected, freqs, fs48)),
    )
    safe_preamp_db = -max_filter_db - headroom_db
    return min(requested_preamp_db, safe_preamp_db)


def select_filters_greedy(filters: List[Filter], max_sections: int) -> Tuple[List[Filter], List[Filter]]:
    freqs = logspace(20.0, 20000.0, 192)
    fs = DEFAULT_TONE_FS_441
    target_db = response_db_for_filters(filters, freqs, fs)
    selected_indexes: List[int] = []
    remaining = set(range(len(filters)))

    while remaining and len(selected_indexes) < max_sections:
        best_index = None
        best_error = None
        for index in sorted(remaining):
            trial_indexes = sorted(selected_indexes + [index])
            trial = [filters[i] for i in trial_indexes]
            error = rms_error_db(trial, target_db, freqs, fs)
            if best_error is None or error < best_error:
                best_error = error
                best_index = index
        selected_indexes.append(best_index)
        remaining.remove(best_index)

    selected_indexes = sorted(selected_indexes)
    selected_set = set(selected_indexes)
    selected = [filters[index] for index in selected_indexes]
    ignored = [f for index, f in enumerate(filters) if index not in selected_set]
    return selected, ignored


def select_filters_best(filters: List[Filter], max_sections: int) -> Tuple[List[Filter], List[Filter]]:
    freqs = logspace(20.0, 20000.0, 192)
    fs = DEFAULT_TONE_FS_441
    target_db = response_db_for_filters(filters, freqs, fs)
    indexes = range(len(filters))
    combination_count = math.comb(len(filters), max_sections)
    if combination_count > 50000:
        print(
            f"warning: best strategy would test {combination_count} combinations; "
            "falling back to greedy"
        )
        return select_filters_greedy(filters, max_sections)

    best_indexes = None
    best_error = None
    for combo in itertools.combinations(indexes, max_sections):
        trial = [filters[i] for i in combo]
        error = rms_error_db(trial, target_db, freqs, fs)
        if best_error is None or error < best_error:
            best_error = error
            best_indexes = combo

    selected_set = set(best_indexes)
    selected = [filters[index] for index in best_indexes]
    ignored = [f for index, f in enumerate(filters) if index not in selected_set]
    return selected, ignored


def select_filters(filters: List[Filter], strategy: str, max_sections: int):
    if max_sections < 1 or max_sections > SECTIONS:
        raise ValueError(f"max_sections must be 1..{SECTIONS}, got {max_sections}")
    if len(filters) <= max_sections or strategy == "first":
        return list(filters[:max_sections]), list(filters[max_sections:])
    if strategy == "greedy":
        return select_filters_greedy(filters, max_sections)
    if strategy == "best":
        return select_filters_best(filters, max_sections)
    ranked = sorted(
        enumerate(filters),
        key=lambda item: (-filter_score(item[1], strategy), item[0]),
    )
    selected_indexes = sorted(index for index, _filter in ranked[:max_sections])
    selected_set = set(selected_indexes)
    selected = [filters[index] for index in selected_indexes]
    ignored = [f for index, f in enumerate(filters) if index not in selected_set]
    return selected, ignored


def render_half(filters: Iterable[Filter], fs: float, preamp_db: float):
    sections = identity_sections()
    selected = list(filters)[:SECTIONS]
    for i, f in enumerate(selected):
        sections[i] = coefficients(f, fs)
    sections = distribute_preamp_for_q37(sections, preamp_db)

    words = []
    for section in sections:
        words.extend(section)
    words.extend([0.0] * (HALF_WORDS - len(words)))
    return b"".join(encode_q37(v) for v in words)


def render(
    filters: List[Filter],
    preamp_db: float,
    fs441: float,
    fs48: float,
    with_checksum: bool,
    filter_strategy: str = "first",
    max_sections: int = SECTIONS,
):
    selected, ignored = select_filters(filters, filter_strategy, max_sections)
    if ignored:
        selected_desc = ", ".join(f"{f.number or '?'}:{f.kind}@{f.freq:g}Hz/{f.gain:+g}dB" for f in selected)
        ignored_desc = ", ".join(f"{f.number or '?'}:{f.kind}@{f.freq:g}Hz/{f.gain:+g}dB" for f in ignored)
        print(
            f"warning: selected {len(selected)}/{len(filters)} filters "
            f"with strategy={filter_strategy}: {selected_desc}; ignored: {ignored_desc}"
        )
    body = render_half(selected, fs441, preamp_db) + render_half(selected, fs48, preamp_db)
    assert len(body) == CHUNK_SIZE
    if with_checksum:
        body += struct.pack("<II", *checksum(body))
    return body


def dump_coefficients(blob: bytes):
    if len(blob) in (CHUNK_SIZE + CHECKSUM_SIZE,):
        blob = blob[:CHUNK_SIZE]
    if len(blob) != CHUNK_SIZE:
        raise ValueError(f"expected {CHUNK_SIZE} or {CHUNK_SIZE + CHECKSUM_SIZE} bytes")
    for half in range(2):
        print(f"half {half}")
        off = half * HALF_SIZE
        for sec in range(SECTIONS):
            vals = []
            for k in range(5):
                word = blob[off + (sec * 5 + k) * 5:off + (sec * 5 + k + 1) * 5]
                vals.append(decode_q37(word))
            print(sec, " ".join(f"{v:+.9f}" for v in vals))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="AutoEq-style filter text")
    parser.add_argument("output", type=Path, help="output PEQ blob")
    parser.add_argument(
        "--fs441",
        type=float,
        default=DEFAULT_TONE_FS_441,
        help="tone-DSP coefficient rate for the 44.1k-family half (default: 176400)",
    )
    parser.add_argument(
        "--fs48",
        type=float,
        default=DEFAULT_TONE_FS_48,
        help="tone-DSP coefficient rate for the 48k-family half (default: 192000)",
    )
    parser.add_argument("--body-only", action="store_true", help="write only 320-byte body, without checksum")
    parser.add_argument("--filter-strategy", choices=("first", "largest", "wide", "greedy", "best"), default="first", help="how to choose filters when input has more than five")
    parser.add_argument("--max-sections", type=int, default=SECTIONS, help=f"number of biquad sections to use, 1..{SECTIONS}")
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
    parser.add_argument("--dump", action="store_true", help="print decoded coefficients after writing")
    args = parser.parse_args()

    requested_preamp, filters = parse_autoeq(args.input.read_text())
    preamp = requested_preamp
    if not args.preserve_preamp:
        preamp = limit_preamp_for_headroom(
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
    blob = render(filters, preamp, args.fs441, args.fs48, not args.body_only, args.filter_strategy, args.max_sections)
    args.output.write_bytes(blob)
    print(
        f"requested_preamp_db={requested_preamp} applied_preamp_db={preamp} "
        f"filters={len(filters)} strategy={args.filter_strategy} "
        f"max_sections={args.max_sections} fs441={args.fs441:g} fs48={args.fs48:g} "
        f"written={args.output} bytes={len(blob)}"
    )
    if args.dump:
        dump_coefficients(blob)


if __name__ == "__main__":
    main()
