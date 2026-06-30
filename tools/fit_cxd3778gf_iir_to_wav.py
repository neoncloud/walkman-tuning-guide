#!/usr/bin/env python3
"""把 AutoEq minimum-phase WAV 拟合成 CXD3778GF 可写入的完整 tone table。

这个工具使用受限的 RBJ EQ 结构（LSC/PK/HSC）拟合目标冲击响应的幅频响应。
它的定位是“安全、可解释的基线算法”：每一段都是常见 EQ biquad，不会产生
自由 SOS 那种靠巨大中间增益互相抵消的危险结构。

输出内容包括：
  - 320 字节 tone chunk（两半分别对应 44.1k 和 48k 系列）
  - 328 字节带 Sony checksum 的 chunk
  - 2888 字节完整 tc_*.tbl，默认同时替换 ng/sg
  - SVG/CSV 拟合图和误差曲线
  - JSON metadata，记录算法、参数、误差和关键频点

可选的 `--refine-from-rbj --sensitive-weight ...` 会先用原始 RBJ 权重得到
一个可解释的 5 段起点，再从这个 IIR 参数继续优化，并提高 1 kHz 到 6 kHz
人耳敏感频段的误差权重。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.optimize import differential_evolution, least_squares

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

import autoeq_to_cxd3778gf_peq as peq  # noqa: E402
import cxd3778gf_tct_tool as tct  # noqa: E402


# 默认尝试的 RBJ 拓扑。每个拓扑必须正好 5 段，因为 CXD3778GF 已验证只执行
# 每个 half 的前 25 个 Q37 word，也就是 5 个 biquad。
DEFAULT_TOPOLOGIES = (
    "LSC,PK,PK,PK,PK",
    "LSC,PK,PK,PK,HSC",
    "PK,PK,PK,PK,PK",
)

KEY_FREQS = (20, 31.5, 63, 100, 200, 500, 1000, 2000, 4000, 8000, 10000, 16000, 20000)


def logspace(start: float, stop: float, count: int) -> np.ndarray:
    """生成对数频率网格。耳机校正更适合在 log-frequency 上评价误差。"""
    return np.logspace(math.log10(start), math.log10(stop), count)


def load_target(path: Path, fs_expected: float, nfft: int, freqs: np.ndarray) -> np.ndarray:
    """读取 minimum-phase WAV，并插值得到目标 dB 幅频响应。"""
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


def params_to_filters(params: np.ndarray, kinds: list[str]) -> tuple[float, list[peq.Filter]]:
    """把优化参数还原成全局增益和 RBJ 滤波器列表。"""
    global_gain = float(params[0])
    filters: list[peq.Filter] = []
    offset = 1
    for index, kind in enumerate(kinds, start=1):
        freq = float(10.0 ** params[offset])
        gain = float(params[offset + 1])
        q = float(params[offset + 2])
        filters.append(peq.Filter(kind=kind, freq=freq, gain=gain, q=q, number=index))
        offset += 3
    return global_gain, filters


def filters_response_db(filters: list[peq.Filter], preamp_db: float, freqs: np.ndarray, fs: float) -> np.ndarray:
    """计算 RBJ 滤波器级联后的 dB 响应，并叠加全局 preamp。"""
    values = np.array(peq.response_db_for_filters(filters, freqs.tolist(), fs), dtype=np.float64)
    return values + preamp_db


def initial_params(kinds: list[str], defaults: list[peq.Filter] | None, preamp_db: float) -> np.ndarray:
    """构造 least_squares 初值；优先使用同目录 AutoEq PEQ 作为合理起点。"""
    params = [preamp_db]
    fallback_freqs = [105.0, 74.0, 449.0, 2871.0, 5745.0]
    for index, kind in enumerate(kinds):
        src = defaults[index] if defaults and index < len(defaults) else None
        freq = src.freq if src else fallback_freqs[min(index, len(fallback_freqs) - 1)]
        gain = src.gain if src else 0.0
        q = src.q if src else (0.7 if kind in ("LSC", "HSC") else 1.0)
        params.extend([math.log10(freq), gain, q])
    return np.array(params, dtype=np.float64)


def bounds_for(kinds: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """给不同滤波器类型设置保守边界，避免跑到不自然的高 Q/极端频点。"""
    lower = [-12.0]
    upper = [6.0]
    for kind in kinds:
        if kind == "LSC":
            freq_min, freq_max = 20.0, 1000.0
        elif kind == "HSC":
            freq_min, freq_max = 3000.0, 20000.0
        else:
            freq_min, freq_max = 20.0, 20000.0
        lower.extend([math.log10(freq_min), -18.0, 0.25])
        upper.extend([math.log10(freq_max), 18.0, 1.0 if kind in ("LSC", "HSC") else 8.0])
    return np.array(lower, dtype=np.float64), np.array(upper, dtype=np.float64)


def write_fit_csv(path: Path, freqs: np.ndarray, target_db: np.ndarray, fitted_db: np.ndarray) -> None:
    """写出 target / fitted / error 采样点，方便后续二次分析。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    error_db = fitted_db - target_db
    rows = ["frequency_hz,target_db,fitted_iir_db,error_db"]
    rows.extend(
        f"{freq:.8g},{target:.8g},{fitted:.8g},{error:.8g}"
        for freq, target, fitted, error in zip(freqs, target_db, fitted_db, error_db)
    )
    path.write_text("\n".join(rows) + "\n")


def write_fit_svg(
    path: Path,
    freqs: np.ndarray,
    target_db: np.ndarray,
    fitted_db: np.ndarray,
    sensitive_band: tuple[float, float] | None = None,
) -> None:
    """写出一张无需 matplotlib 的 SVG 图，显示目标、拟合和误差。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    error_db = fitted_db - target_db
    width, height = 1280, 760
    ml, mr, mt, mb = 78, 42, 48, 68
    gap = 40
    main_h = 420
    err_h = height - mt - mb - main_h - gap
    plot_w = width - ml - mr
    x0, x1 = math.log10(20.0), math.log10(20000.0)
    y_min = min(math.floor(min(float(target_db.min()), float(fitted_db.min())) - 1.0), -8)
    y_max = max(math.ceil(max(float(target_db.max()), float(fitted_db.max())) + 1.0), 2)
    err_abs = max(2.0, math.ceil(float(np.max(np.abs(error_db))) * 2.0) / 2.0)

    def sx(freq: float) -> float:
        return ml + (math.log10(freq) - x0) / (x1 - x0) * plot_w

    def sy_main(db: float) -> float:
        return mt + (y_max - db) / (y_max - y_min) * main_h

    err_top = mt + main_h + gap

    def sy_err(db: float) -> float:
        return err_top + (err_abs - db) / (2.0 * err_abs) * err_h

    def polyline(values: np.ndarray, sy) -> str:
        return " ".join(f"{sx(float(freq)):.2f},{sy(float(value)):.2f}" for freq, value in zip(freqs, values))

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fbfbf8"/>',
        f'<text x="{ml}" y="30" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#111827">CXD3778GF RBJ IIR 拟合结果</text>',
    ]
    major_freqs = (20, 100, 1000, 10000, 20000)
    grid_freqs = (20, 30, 40, 50, 60, 80, 100, 200, 300, 400, 500, 600, 800, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 20000)
    for top, h in ((mt, main_h), (err_top, err_h)):
        if sensitive_band is not None:
            bx0 = sx(sensitive_band[0])
            bw = sx(sensitive_band[1]) - bx0
            svg.append(f'<rect x="{bx0:.2f}" y="{top}" width="{bw:.2f}" height="{h}" fill="#fef3c7" opacity="0.45"/>')
        for freq in grid_freqs:
            x = sx(freq)
            major = freq in major_freqs
            svg.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + h}" stroke="{"#c9c9c9" if major else "#e7e2d8"}" stroke-width="{1.1 if major else 0.7}"/>')
        svg.append(f'<rect x="{ml}" y="{top}" width="{plot_w}" height="{h}" fill="none" stroke="#111827" stroke-width="1"/>')
    for db in range(y_min, y_max + 1):
        y = sy_main(db)
        major = db == 0
        svg.append(f'<line x1="{ml}" y1="{y:.2f}" x2="{ml + plot_w}" y2="{y:.2f}" stroke="{"#9ca3af" if major else "#e3dfd7"}" stroke-width="{1.3 if major else 0.8}"/>')
        svg.append(f'<text x="{ml - 10}" y="{y + 4:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#374151">{db}</text>')
    for db in np.linspace(-err_abs, err_abs, 5):
        y = sy_err(float(db))
        major = abs(float(db)) < 1e-9
        svg.append(f'<line x1="{ml}" y1="{y:.2f}" x2="{ml + plot_w}" y2="{y:.2f}" stroke="{"#9ca3af" if major else "#e3dfd7"}" stroke-width="{1.3 if major else 0.8}"/>')
        svg.append(f'<text x="{ml - 10}" y="{y + 4:.2f}" text-anchor="end" font-family="Arial, sans-serif" font-size="12" fill="#374151">{db:.1f}</text>')
    for freq, label in ((20, "20"), (100, "100"), (1000, "1k"), (10000, "10k"), (20000, "20k")):
        svg.append(f'<text x="{sx(freq):.2f}" y="{height - 22}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#374151">{label}</text>')
    svg.append(f'<polyline points="{polyline(target_db, sy_main)}" fill="none" stroke="#2563eb" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')
    svg.append(f'<polyline points="{polyline(fitted_db, sy_main)}" fill="none" stroke="#dc2626" stroke-width="2.0" stroke-linejoin="round" stroke-linecap="round" stroke-dasharray="8 5"/>')
    svg.append(f'<polyline points="{polyline(error_db, sy_err)}" fill="none" stroke="#111827" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>')
    svg.append(f'<text x="{ml + 12}" y="{mt + 22}" font-family="Arial, sans-serif" font-size="13" fill="#2563eb">目标 WAV</text>')
    svg.append(f'<text x="{ml + 112}" y="{mt + 22}" font-family="Arial, sans-serif" font-size="13" fill="#dc2626">拟合 IIR</text>')
    if sensitive_band is not None:
        svg.append(f'<text x="{sx(sensitive_band[0]) + 8:.2f}" y="{mt + main_h - 12}" font-family="Arial, sans-serif" font-size="12" fill="#92400e">敏感频段加权</text>')
    svg.append(f'<text x="{ml + 12}" y="{err_top + 22}" font-family="Arial, sans-serif" font-size="13" fill="#111827">误差 = 拟合 - 目标</text>')
    svg.append(f'<text x="{ml + plot_w / 2:.2f}" y="{height - 8}" text-anchor="middle" font-family="Arial, sans-serif" font-size="13" fill="#111827">频率（Hz，对数坐标）</text>')
    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n")


def base_weights(freqs: np.ndarray) -> np.ndarray:
    """原始 RBJ baseline 权重：超高频和极低频略低。"""
    weights = np.ones_like(freqs)
    weights[freqs > 10000.0] *= 0.65
    weights[freqs < 35.0] *= 0.75
    return weights


def make_weights(freqs: np.ndarray, sensitive_band: tuple[float, float] | None, sensitive_weight: float) -> np.ndarray:
    """构造最终优化权重，可额外提高人耳敏感频段权重。"""
    weights = base_weights(freqs)
    if sensitive_band is not None and sensitive_weight > 0:
        lo, hi = sensitive_band
        weights[(freqs >= lo) & (freqs <= hi)] *= sensitive_weight
    return weights


def residuals(
    params: np.ndarray,
    kinds: list[str],
    freqs: np.ndarray,
    target_db: np.ndarray,
    fs: float,
    weights: np.ndarray,
) -> np.ndarray:
    """优化残差：加权 dB 误差。"""
    preamp_db, filters = params_to_filters(params, kinds)
    got = filters_response_db(filters, preamp_db, freqs, fs)
    return (got - target_db) * weights


def fit_topology(
    kinds: list[str],
    defaults: list[peq.Filter] | None,
    preamp_db: float,
    freqs: np.ndarray,
    target_db: np.ndarray,
    fs: float,
    global_search: bool,
    weights: np.ndarray,
    refine_from_rbj: bool,
) -> tuple[float, float, np.ndarray]:
    """拟合一种拓扑，返回加权 RMS 和最优参数。"""
    lower, upper = bounds_for(kinds)
    starts = [initial_params(kinds, defaults, preamp_db)]
    if global_search:
        result = differential_evolution(
            lambda p: float(np.mean(residuals(p, kinds, freqs, target_db, fs, weights) ** 2)),
            bounds=list(zip(lower, upper)),
            maxiter=80,
            popsize=10,
            polish=False,
            seed=3778,
            workers=1,
            updating="immediate",
            tol=1e-5,
        )
        starts.append(result.x)

    best_cost = None
    best_base_cost = None
    best_params = None
    for start in starts:
        start = np.minimum(np.maximum(start, lower), upper)
        if refine_from_rbj:
            # 第一阶段：用原始 RBJ baseline 权重得到一个稳定、可解释的起点。
            baseline = least_squares(
                residuals,
                start,
                args=(kinds, freqs, target_db, fs, base_weights(freqs)),
                bounds=(lower, upper),
                max_nfev=5000,
                xtol=1e-9,
                ftol=1e-9,
                gtol=1e-9,
            )
            start = baseline.x
        result = least_squares(
            residuals,
            start,
            args=(kinds, freqs, target_db, fs, weights),
            bounds=(lower, upper),
            max_nfev=5000,
            xtol=1e-9,
            ftol=1e-9,
            gtol=1e-9,
        )
        cost = float(np.sqrt(np.mean(residuals(result.x, kinds, freqs, target_db, fs, weights) ** 2)))
        base_cost = float(np.sqrt(np.mean(residuals(result.x, kinds, freqs, target_db, fs, base_weights(freqs)) ** 2)))
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_base_cost = base_cost
            best_params = result.x
    assert best_cost is not None and best_base_cost is not None and best_params is not None
    return best_cost, best_base_cost, best_params


def render_chunk(filters: list[peq.Filter], preamp_db: float, fs441: float, fs48: float) -> bytes:
    """把 5 段 RBJ 滤波器编码为 CXD3778GF 320 字节 chunk。"""
    return peq.render(filters, preamp_db, fs441, fs48, with_checksum=False, filter_strategy="first", max_sections=5)


def build_table(base: Path, chunk: bytes, output: Path, targets: list[str]) -> bytes:
    """基于 stock table 替换指定 chunk，并写出完整 2888 字节 table。"""
    body, _ = tct.read_table(base)
    chunks = [body[i * tct.CHUNK_SIZE:(i + 1) * tct.CHUNK_SIZE] for i in range(len(tct.TABLE_NAMES))]
    for name in targets:
        chunks[tct.TABLE_NAMES.index(name)] = chunk
    new_body = b"".join(chunks)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(new_body + struct.pack("<II", *tct.checksum(new_body)))
    return new_body


def main() -> None:
    parser = argparse.ArgumentParser(description="把 minimum-phase WAV 拟合为 RBJ 5-biquad CXD3778GF 完整表")
    parser.add_argument("wav", type=Path, help="目标 correction impulse WAV，通常来自 AutoEq minimum phase 48000Hz.wav")
    parser.add_argument("output_table", type=Path, help="输出完整 2888-byte tc_*.tbl")
    parser.add_argument("--base-table", type=Path, required=True, help="stock 2888-byte tc_*.tbl")
    parser.add_argument("--chunk", type=Path, required=True, help="输出 320-byte raw chunk；同目录会额外写 .tbl checksum chunk")
    parser.add_argument("--metadata", type=Path, required=True, help="输出 JSON 元数据")
    parser.add_argument("--autoeq-peq", type=Path, help="可选 AutoEq ParametricEQ.txt，用作初值")
    parser.add_argument("--fs441", type=float, default=44100.0)
    parser.add_argument("--fs48", type=float, default=48000.0)
    parser.add_argument("--points", type=int, default=384)
    parser.add_argument("--topology", action="append", default=[], help="5 段拓扑，例如 LSC,PK,PK,PK,HSC；可重复")
    parser.add_argument("--global-search", action="store_true", help="先做 differential evolution 再 least_squares，较慢")
    parser.add_argument("--plot-svg", type=Path)
    parser.add_argument("--plot-csv", type=Path)
    parser.add_argument("--targets", default="ng,sg", help="要替换的 table chunk 名称，默认 ng,sg")
    parser.add_argument("--refine-from-rbj", action="store_true", help="先做原始 RBJ baseline 拟合，再从该 IIR 起点做加权优化")
    parser.add_argument("--sensitive-band", default="1000,6000", help="加权频段，默认 1000,6000；设为 none 关闭")
    parser.add_argument("--sensitive-weight", type=float, default=1.0, help="敏感频段额外权重倍率，默认 1.0")
    args = parser.parse_args()

    targets = [item.strip() for item in args.targets.split(",") if item.strip()]
    for target in targets:
        if target not in tct.TABLE_NAMES:
            raise SystemExit(f"unknown target {target!r}; valid: {', '.join(tct.TABLE_NAMES)}")

    preamp0 = 0.0
    defaults = None
    if args.autoeq_peq:
        preamp0, defaults = peq.parse_autoeq(args.autoeq_peq.read_text())
        if defaults:
            defaults = defaults[:5]

    freqs = logspace(20.0, 20000.0, args.points)
    target_db = load_target(args.wav, args.fs48, 65536, freqs)
    topologies = args.topology or list(DEFAULT_TOPOLOGIES)
    if args.sensitive_band.lower() in ("none", "off", "0"):
        sensitive_band = None
    else:
        parts = [float(item.strip()) for item in args.sensitive_band.split(",")]
        if len(parts) != 2 or not (20.0 <= parts[0] < parts[1] <= 20000.0):
            raise SystemExit("--sensitive-band must be like 1000,6000 within 20..20000 Hz")
        sensitive_band = (parts[0], parts[1])
    weights = make_weights(freqs, sensitive_band, args.sensitive_weight)

    results = []
    for topology in topologies:
        kinds = [item.strip().upper() for item in topology.split(",") if item.strip()]
        if len(kinds) != 5:
            raise SystemExit(f"{topology!r}: expected exactly five section types")
        cost, base_cost, params = fit_topology(
            kinds,
            defaults,
            preamp0,
            freqs,
            target_db,
            args.fs48,
            args.global_search,
            weights,
            args.refine_from_rbj,
        )
        results.append((cost, base_cost, topology, kinds, params))
        print(f"topology={topology} weighted_rms={cost:.4f}dB base_weight_rms={base_cost:.4f}dB")

    cost, base_cost, topology, kinds, params = sorted(results, key=lambda item: item[0])[0]
    preamp_db, filters = params_to_filters(params, kinds)
    chunk = render_chunk(filters, preamp_db, args.fs441, args.fs48)
    args.chunk.parent.mkdir(parents=True, exist_ok=True)
    args.chunk.write_bytes(chunk)
    args.chunk.with_suffix(".tbl").write_bytes(chunk + struct.pack("<II", *tct.checksum(chunk)))
    new_body = build_table(args.base_table, chunk, args.output_table, targets)

    got_db = filters_response_db(filters, preamp_db, freqs, args.fs48)
    err = got_db - target_db
    if args.plot_svg:
        write_fit_svg(args.plot_svg, freqs, target_db, got_db, sensitive_band if args.sensitive_weight != 1.0 else None)
    if args.plot_csv:
        write_fit_csv(args.plot_csv, freqs, target_db, got_db)

    metadata = {
        "method": "RBJ 5-biquad least_squares fit to minimum-phase WAV magnitude",
        "optimization": {
            "refine_from_rbj": bool(args.refine_from_rbj),
            "sensitive_band_hz": list(sensitive_band) if sensitive_band is not None else None,
            "sensitive_weight": float(args.sensitive_weight),
            "base_weight_rms_db": base_cost,
            "weighted_rms_db": cost,
        },
        "wav": str(args.wav),
        "base_table": str(args.base_table),
        "output_table": str(args.output_table),
        "chunk": str(args.chunk),
        "targets": targets,
        "topology": topology,
        "weighted_rms_db": cost,
        "base_weight_rms_db": base_cost,
        "unweighted_rms_db": float(np.sqrt(np.mean(err ** 2))),
        "max_abs_error_db": float(np.max(np.abs(err))),
        "sensitive_band_rms_db": None,
        "preamp_db": preamp_db,
        "filters": [asdict(f) for f in filters],
        "chunk_md5": hashlib.md5(chunk).hexdigest(),
        "body_md5": hashlib.md5(new_body).hexdigest(),
        "key_points": [],
        "reproduce_hint": {
            "script": "experiments/reproduce/10_blessing3_rbj_wav_fit.sh",
            "cwd": str(Path.cwd()),
        },
    }
    if sensitive_band is not None:
        mask = (freqs >= sensitive_band[0]) & (freqs <= sensitive_band[1])
        metadata["sensitive_band_rms_db"] = float(np.sqrt(np.mean(err[mask] ** 2)))
    for hz in KEY_FREQS:
        idx = int(np.argmin(np.abs(freqs - hz)))
        metadata["key_points"].append(
            {
                "frequency_hz": float(freqs[idx]),
                "target_db": float(target_db[idx]),
                "fitted_db": float(got_db[idx]),
                "error_db": float(err[idx]),
            }
        )
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(metadata, indent=2) + "\n")

    print(f"selected_topology={topology}")
    print(f"preamp_db={preamp_db:.4f}")
    for filt in filters:
        print(f"Filter {filt.number}: ON {filt.kind} Fc {filt.freq:.2f} Hz Gain {filt.gain:+.3f} dB Q {filt.q:.3f}")
    if metadata["sensitive_band_rms_db"] is not None:
        print(f"sensitive_band_rms={metadata['sensitive_band_rms_db']:.4f}dB band={sensitive_band[0]:.0f}-{sensitive_band[1]:.0f}Hz weight={args.sensitive_weight:g}")
    print(f"unweighted_rms={metadata['unweighted_rms_db']:.4f}dB max_abs={metadata['max_abs_error_db']:.4f}dB")
    print(f"chunk_md5={metadata['chunk_md5']}")
    print(f"body_md5={metadata['body_md5']}")
    print(f"chunk={args.chunk}")
    print(f"output_table={args.output_table}")
    print(f"metadata={args.metadata}")
    if args.plot_svg:
        print(f"plot_svg={args.plot_svg}")
    if args.plot_csv:
        print(f"plot_csv={args.plot_csv}")


if __name__ == "__main__":
    main()
