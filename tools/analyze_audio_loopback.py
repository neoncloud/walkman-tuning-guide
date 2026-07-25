#!/usr/bin/env python3
"""分析 CXD3778GF 扫频录音，并比较实测频响与 TBL 理论频响。"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib
import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate, correlation_lags, hilbert, resample_poly

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


TOOL_DIR = Path(__file__).resolve().parent
PLOT_TOOL_PATH = TOOL_DIR / "plot_cxd3778gf_tct_response.py"
TABLE_NAMES = ("nh", "ng", "nnw500", "nnw750", "nnc31", "sg", "snw500", "snw750", "snc31")
CHUNK_SIZE = 320


def load_plot_tool():
    spec = importlib.util.spec_from_file_location("cxd3778gf_plot_tool", PLOT_TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {PLOT_TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLOT_TOOL = load_plot_tool()


@dataclass
class Capture:
    label: str
    wav_path: Path
    metadata_path: Path
    metadata: dict
    sample_rate: int
    samples: np.ndarray


@dataclass
class Profile:
    label: str
    capture: Capture
    table_path: Path


def parse_mapping(text: str, expected_parts: int) -> list[str]:
    parts = text.split("=", expected_parts - 1)
    if len(parts) != expected_parts or any(not part for part in parts):
        raise argparse.ArgumentTypeError(
            f"参数应包含 {expected_parts} 段并以 '=' 分隔：{text!r}"
        )
    return parts


def read_capture(label: str, wav_path: Path) -> Capture:
    metadata_path = wav_path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    sample_rate, samples = wavfile.read(wav_path)
    if samples.ndim == 1:
        samples = samples[:, None]
    if not np.issubdtype(samples.dtype, np.floating):
        max_value = float(np.iinfo(samples.dtype).max)
        samples = samples.astype(np.float64) / max_value
    else:
        samples = samples.astype(np.float64)
    channel = int(metadata["selected_channel_zero_based"])
    return Capture(
        label=label,
        wav_path=wav_path,
        metadata_path=metadata_path,
        metadata=metadata,
        sample_rate=int(sample_rate),
        samples=samples[:, channel],
    )


def read_stimulus(capture: Capture) -> np.ndarray:
    stimulus_path = capture.wav_path.parent / capture.metadata["stimulus_path"]
    sample_rate, stimulus = wavfile.read(stimulus_path)
    if stimulus.ndim == 2:
        # 单声道探针可能只播放左或右；选择实际有能量的一侧作为对齐参考。
        channel_energy = np.sum(np.square(stimulus.astype(np.float64)), axis=0)
        stimulus = stimulus[:, int(np.argmax(channel_energy))]
    stimulus = stimulus.astype(np.float64)
    if sample_rate != capture.sample_rate:
        divisor = math.gcd(int(sample_rate), int(capture.sample_rate))
        stimulus = resample_poly(
            stimulus,
            capture.sample_rate // divisor,
            int(sample_rate) // divisor,
        )
    return stimulus


def aligned_sweeps(capture: Capture, stimulus: np.ndarray) -> tuple[list[np.ndarray], list[dict]]:
    """用互相关估计每段扫频的回环延迟，并提取与激励等长的录音段。"""
    sample_rate = capture.sample_rate
    sweep_samples = int(capture.metadata["sweep_samples"])
    starts = [int(value) for value in capture.metadata["sweep_starts"]]
    downsample = max(1, sample_rate // 6000)
    search_before = int(round(0.05 * sample_rate))
    # WDM-KS 的两个独立流首次启动时可能相差接近 1 秒，故保留较宽搜索窗。
    search_after = int(round(1.50 * sample_rate))
    aligned: list[np.ndarray] = []
    diagnostics: list[dict] = []

    for repetition, expected_start in enumerate(starts, start=1):
        reference = stimulus[expected_start:expected_start + sweep_samples]
        candidate_start = max(0, expected_start - search_before)
        candidate_end = min(
            len(capture.samples),
            expected_start + sweep_samples + search_after,
        )
        candidate = capture.samples[candidate_start:candidate_end]
        reference_ds = reference[::downsample]
        candidate_ds = candidate[::downsample]
        corr = correlate(candidate_ds, reference_ds, mode="valid", method="fft")
        lags = correlation_lags(len(candidate_ds), len(reference_ds), mode="valid")
        best = int(np.argmax(np.abs(corr)))
        start = candidate_start + int(lags[best]) * downsample
        start = max(0, min(start, len(capture.samples) - sweep_samples))
        extracted = capture.samples[start:start + sweep_samples]

        ref_norm = float(np.linalg.norm(reference_ds))
        segment_ds = candidate_ds[lags[best]:lags[best] + len(reference_ds)]
        segment_norm = float(np.linalg.norm(segment_ds))
        normalized_corr = float(abs(corr[best]) / max(ref_norm * segment_norm, 1e-30))
        diagnostics.append(
            {
                "repetition": repetition,
                "expected_start_sample": expected_start,
                "detected_start_sample": start,
                "latency_ms": (start - expected_start) * 1000.0 / sample_rate,
                "normalized_correlation": normalized_corr,
            }
        )
        aligned.append(extracted)
    return aligned, diagnostics


def sweep_response(capture: Capture, frequencies: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    """用与扫频相干的复数解调提取幅频响应，并抑制录音端宽带噪声。"""
    stimulus = read_stimulus(capture)
    aligned, diagnostics = aligned_sweeps(capture, stimulus)
    sweep_samples = int(capture.metadata["sweep_samples"])
    sweep_seconds = float(capture.metadata["sweep_seconds"])
    start_hz = float(capture.metadata["start_hz"])
    end_hz = float(capture.metadata["end_hz"])
    reference_start = int(capture.metadata["sweep_starts"][0])
    reference = stimulus[reference_start:reference_start + sweep_samples]
    analytic_reference = hilbert(reference)
    ratio_curves = []
    log_span = math.log(end_hz / start_hz)

    for extracted in aligned:
        values = []
        for frequency in frequencies:
            time_s = sweep_seconds * math.log(frequency / start_hz) / log_span
            center = int(round(time_s * capture.sample_rate))
            # 约 1/8 倍频程的时间窗，并让低频至少覆盖 8 个周期。参考信号
            # 本身仍是 chirp，相干解调不会把窗内的扫频变化当成带外能量。
            octave_window_s = sweep_seconds * math.log(2.0) / log_span / 8.0
            half_window_s = max(octave_window_s / 2.0, 4.0 / frequency)
            half = max(8, int(round(half_window_s * capture.sample_rate)))
            lo = max(0, center - half)
            hi = min(sweep_samples, center + half + 1)
            window = np.hanning(hi - lo)
            reference_segment = analytic_reference[lo:hi]
            recorded_segment = extracted[lo:hi]
            numerator = abs(
                np.sum(window * recorded_segment * np.conj(reference_segment))
            )
            denominator = 0.5 * float(
                np.sum(window * np.square(np.abs(reference_segment)))
            )
            gain = float(numerator / max(denominator, 1e-30))
            values.append(20.0 * math.log10(max(gain, 1e-15)))
        ratio_curves.append(values)
    return np.median(np.asarray(ratio_curves), axis=0), diagnostics


def periodic_noise_response(
    capture: Capture, frequencies: np.ndarray
) -> tuple[np.ndarray, list[dict]]:
    """从周期宽带信号提取传递函数；每个周期和频带都取中位数以抑制噪声。"""
    stimulus = read_stimulus(capture)
    sample_rate = capture.sample_rate
    active_start = int(capture.metadata["active_start_sample"])
    period_samples = int(capture.metadata["period_samples"])
    periods = int(capture.metadata["periods"])
    settle_periods = int(capture.metadata["settle_periods"])
    reference = stimulus[active_start:active_start + period_samples]

    downsample = max(1, sample_rate // 6000)
    search_before = int(round(0.05 * sample_rate))
    # 搜索窗小于一个周期，避免把第二个完全相同的周期误认成第一个。
    search_after = min(
        period_samples - downsample,
        int(round(1.25 * sample_rate)),
    )
    candidate_start = max(0, active_start - search_before)
    candidate_end = min(
        len(capture.samples),
        active_start + period_samples + search_after,
    )
    reference_ds = reference[::downsample]
    candidate_ds = capture.samples[candidate_start:candidate_end:downsample]
    corr = correlate(candidate_ds, reference_ds, mode="valid", method="fft")
    lags = correlation_lags(len(candidate_ds), len(reference_ds), mode="valid")
    best = int(np.argmax(np.abs(corr)))
    detected_start = candidate_start + int(lags[best]) * downsample
    segment_ds = candidate_ds[lags[best]:lags[best] + len(reference_ds)]
    normalized_corr = float(
        abs(corr[best])
        / max(
            float(np.linalg.norm(reference_ds) * np.linalg.norm(segment_ds)),
            1e-30,
        )
    )

    reference_fft = np.fft.rfft(reference)
    bin_frequencies = np.fft.rfftfreq(period_samples, d=1.0 / sample_rate)
    active_bins = (
        (bin_frequencies >= float(capture.metadata["start_hz"]))
        & (bin_frequencies <= float(capture.metadata["end_hz"]))
        & (np.abs(reference_fft) > np.max(np.abs(reference_fft)) * 1e-10)
    )
    active_bin_frequencies = bin_frequencies[active_bins]
    period_curves = []
    used_periods = 0
    for period_index in range(settle_periods, periods):
        start = detected_start + period_index * period_samples
        end = start + period_samples
        if end > len(capture.samples):
            break
        recorded_fft = np.fft.rfft(capture.samples[start:end])
        ratio_db = 20.0 * np.log10(
            np.maximum(
                np.abs(recorded_fft[active_bins])
                / np.maximum(np.abs(reference_fft[active_bins]), 1e-30),
                1e-15,
            )
        )
        smoothed = []
        for frequency in frequencies:
            lo = frequency / (2.0 ** (1.0 / 24.0))
            hi = frequency * (2.0 ** (1.0 / 24.0))
            band = (active_bin_frequencies >= lo) & (active_bin_frequencies <= hi)
            if np.any(band):
                smoothed.append(float(np.median(ratio_db[band])))
            else:
                smoothed.append(
                    float(
                        np.interp(
                            math.log(frequency),
                            np.log(active_bin_frequencies),
                            ratio_db,
                        )
                    )
                )
        period_curves.append(smoothed)
        used_periods += 1
    if not period_curves:
        raise ValueError(f"{capture.wav_path}: 没有完整的可分析周期")

    diagnostics = [
        {
            "expected_start_sample": active_start,
            "detected_start_sample": detected_start,
            "latency_ms": (detected_start - active_start) * 1000.0 / sample_rate,
            "normalized_correlation": normalized_corr,
            "periods_used": used_periods,
        }
    ]
    return np.median(np.asarray(period_curves), axis=0), diagnostics


def capture_response(
    capture: Capture, frequencies: np.ndarray
) -> tuple[np.ndarray, list[dict]]:
    signal_type = capture.metadata.get("signal_type", "log-sweep")
    if signal_type == "log-sweep":
        return sweep_response(capture, frequencies)
    if signal_type == "periodic-noise":
        return periodic_noise_response(capture, frequencies)
    raise ValueError(f"{capture.wav_path}: 不支持的 signal_type={signal_type!r}")


def read_table_sections(path: Path, target: str, half: int) -> list[list[float]]:
    data = path.read_bytes()
    if len(data) == CHUNK_SIZE + 8:
        chunk = data[:CHUNK_SIZE]
    elif len(data) in (CHUNK_SIZE * len(TABLE_NAMES), CHUNK_SIZE * len(TABLE_NAMES) + 8):
        index = TABLE_NAMES.index(target)
        chunk = data[index * CHUNK_SIZE:(index + 1) * CHUNK_SIZE]
    else:
        raise ValueError(f"{path}: 不支持的 TBL/chunk 大小 {len(data)}")
    temporary = path.parent / f".{path.name}.{target}.chunk.tmp"
    try:
        temporary.write_bytes(chunk)
        return PLOT_TOOL.decode_sections(temporary, half)
    finally:
        temporary.unlink(missing_ok=True)


def table_response(path: Path, target: str, half: int, sample_rate: int, frequencies: np.ndarray) -> np.ndarray:
    sections = read_table_sections(path, target, half)
    return np.asarray(
        [PLOT_TOOL.response_db(sections, float(frequency), sample_rate) for frequency in frequencies]
    )


def rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def analyze_metrics(
    frequencies: np.ndarray,
    measured_raw: np.ndarray,
    expected: np.ndarray,
) -> tuple[np.ndarray, dict]:
    valid = (frequencies >= 30.0) & (frequencies <= 18000.0)
    flat_reference = valid & (np.abs(expected) <= 0.30)
    if np.count_nonzero(flat_reference) < 12:
        flat_reference = valid
    global_offset = float(np.median(measured_raw[flat_reference] - expected[flat_reference]))
    measured = measured_raw - global_offset
    error = measured - expected
    sensitive = (frequencies >= 1000.0) & (frequencies <= 6000.0)
    expected_abs_max_index = int(np.argmax(np.abs(expected[valid])))
    valid_indexes = np.flatnonzero(valid)
    focus_index = int(valid_indexes[expected_abs_max_index])
    correlation = float(np.corrcoef(measured[valid], expected[valid])[0, 1])
    metrics = {
        "global_level_offset_removed_db": global_offset,
        "rmse_30_18000_db": rms(error[valid]),
        "mae_30_18000_db": float(np.mean(np.abs(error[valid]))),
        "max_abs_error_30_18000_db": float(np.max(np.abs(error[valid]))),
        "rmse_1000_6000_db": rms(error[sensitive]),
        "correlation_30_18000": correlation,
        "focus_frequency_hz": float(frequencies[focus_index]),
        "expected_at_focus_db": float(expected[focus_index]),
        "measured_at_focus_db": float(measured[focus_index]),
        "error_at_focus_db": float(error[focus_index]),
    }
    return measured, metrics


def render_plot(
    output_path: Path,
    frequencies: np.ndarray,
    results: list[dict],
    repeatability: np.ndarray,
    restore_delta: np.ndarray | None,
) -> None:
    rows = len(results) + 1
    fig, axes = plt.subplots(rows, 2, figsize=(13.2, 3.2 * rows), squeeze=False)
    for row, result in enumerate(results):
        ax_response, ax_error = axes[row]
        ax_response.semilogx(frequencies, result["expected"], label="TBL 理论", linewidth=2.0)
        ax_response.semilogx(frequencies, result["measured"], label="回环实测", linewidth=1.6)
        ax_response.axhline(0.0, color="0.55", linewidth=0.8)
        ax_response.set_title(result["label"])
        ax_response.set_ylabel("相对原厂 / dB")
        ax_response.legend(loc="best")
        ax_response.grid(True, which="both", alpha=0.25)

        error = result["measured"] - result["expected"]
        ax_error.semilogx(frequencies, error, color="tab:red", linewidth=1.4)
        ax_error.axhspan(-1.0, 1.0, color="tab:green", alpha=0.10)
        ax_error.axhline(0.0, color="0.55", linewidth=0.8)
        ax_error.set_title(f"{result['label']}：实测 - 理论")
        ax_error.set_ylabel("误差 / dB")
        ax_error.grid(True, which="both", alpha=0.25)

    ax_repeat, ax_restore = axes[-1]
    ax_repeat.semilogx(frequencies, repeatability, color="tab:purple", linewidth=1.4)
    ax_repeat.axhline(0.0, color="0.55", linewidth=0.8)
    ax_repeat.set_title("两次基线的重复性")
    ax_repeat.set_ylabel("第 2 次 - 第 1 次 / dB")
    ax_repeat.grid(True, which="both", alpha=0.25)

    if restore_delta is not None:
        ax_restore.semilogx(frequencies, restore_delta, color="tab:green", linewidth=1.4)
        ax_restore.axhline(0.0, color="0.55", linewidth=0.8)
        ax_restore.set_title("恢复基线后的差异")
        ax_restore.set_ylabel("恢复后 - 恢复前 / dB")
        ax_restore.grid(True, which="both", alpha=0.25)
    else:
        ax_restore.axis("off")

    for ax in axes.flat:
        if ax.has_data():
            ax.set_xlim(20.0, 20000.0)
            ax.set_xlabel("频率 / Hz")
    fig.tight_layout()
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="append", required=True, metavar="LABEL=WAV")
    parser.add_argument("--profile", action="append", required=True, metavar="LABEL=WAV=TBL")
    parser.add_argument("--stock-after", metavar="LABEL=WAV")
    parser.add_argument("--stock-table", type=Path, required=True)
    parser.add_argument("--target", choices=TABLE_NAMES, default="sg")
    parser.add_argument("--half", type=int, choices=(0, 1), default=1)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument(
        "--dsp-sample-rate",
        type=int,
        help="CXD3778GF tone IIR 的实际运行采样率；USB DAC 实测为 192000 Hz",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    baseline_specs = [parse_mapping(value, 2) for value in args.baseline]
    profile_specs = [parse_mapping(value, 3) for value in args.profile]
    stock_after_spec = parse_mapping(args.stock_after, 2) if args.stock_after else None

    baselines = [read_capture(label, Path(path)) for label, path in baseline_specs]
    profiles = [
        Profile(label, read_capture(label, Path(wav)), Path(table))
        for label, wav, table in profile_specs
    ]
    stock_after = (
        read_capture(stock_after_spec[0], Path(stock_after_spec[1]))
        if stock_after_spec
        else None
    )
    all_captures = [*baselines, *(profile.capture for profile in profiles)]
    if stock_after is not None:
        all_captures.append(stock_after)
    sample_rates = {capture.sample_rate for capture in all_captures}
    if sample_rates != {args.sample_rate}:
        raise SystemExit(f"录音采样率不一致或不是 {args.sample_rate} Hz：{sample_rates}")
    dsp_sample_rate = args.dsp_sample_rate or args.sample_rate

    args.output_dir.mkdir(parents=True, exist_ok=True)
    frequencies = np.geomspace(22.0, 19500.0, 500)
    response_cache: dict[str, np.ndarray] = {}
    diagnostics: dict[str, list[dict]] = {}
    for capture in all_captures:
        response, diag = capture_response(capture, frequencies)
        response_cache[capture.label] = response
        diagnostics[capture.label] = diag

    baseline_stack = np.asarray([response_cache[capture.label] for capture in baselines])
    baseline_mean = np.mean(baseline_stack, axis=0)
    repeatability = (
        baseline_stack[1] - baseline_stack[0]
        if len(baselines) >= 2
        else np.zeros_like(frequencies)
    )
    stock_theory = table_response(
        args.stock_table, args.target, args.half, dsp_sample_rate, frequencies
    )

    results: list[dict] = []
    metrics: dict[str, dict] = {}
    for profile in profiles:
        profile_theory = table_response(
            profile.table_path, args.target, args.half, dsp_sample_rate, frequencies
        )
        expected = profile_theory - stock_theory
        measured_raw = response_cache[profile.label] - baseline_mean
        measured, profile_metrics = analyze_metrics(frequencies, measured_raw, expected)
        results.append(
            {
                "label": profile.label,
                "expected": expected,
                "measured_raw": measured_raw,
                "measured": measured,
            }
        )
        metrics[profile.label] = profile_metrics

    valid = (frequencies >= 30.0) & (frequencies <= 18000.0)
    repeatability_centered = repeatability - np.median(repeatability[valid])
    repeatability_rmse = rms(repeatability_centered[valid])
    restore_delta = None
    restore_rmse = None
    if stock_after is not None:
        restore_delta = response_cache[stock_after.label] - baseline_mean
        restore_delta = restore_delta - np.median(restore_delta[valid])
        restore_rmse = rms(restore_delta[valid])

    csv_path = args.output_dir / "frequency_response.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fp:
        fieldnames = [
            "frequency_hz",
            "stock_mean_db",
            "baseline_repeatability_db",
        ]
        if restore_delta is not None:
            fieldnames.append("stock_after_delta_db")
        for result in results:
            fieldnames.extend(
                [
                    f"{result['label']}_expected_db",
                    f"{result['label']}_measured_raw_db",
                    f"{result['label']}_measured_normalized_db",
                    f"{result['label']}_error_db",
                ]
            )
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for index, frequency in enumerate(frequencies):
            row = {
                "frequency_hz": float(frequency),
                "stock_mean_db": float(baseline_mean[index]),
                "baseline_repeatability_db": float(repeatability_centered[index]),
            }
            if restore_delta is not None:
                row["stock_after_delta_db"] = float(restore_delta[index])
            for result in results:
                row[f"{result['label']}_expected_db"] = float(result["expected"][index])
                row[f"{result['label']}_measured_raw_db"] = float(result["measured_raw"][index])
                row[f"{result['label']}_measured_normalized_db"] = float(result["measured"][index])
                row[f"{result['label']}_error_db"] = float(
                    result["measured"][index] - result["expected"][index]
                )
            writer.writerow(row)

    summary = {
        "frequency_range_for_metrics_hz": [30.0, 18000.0],
        "capture_sample_rate_hz": args.sample_rate,
        "dsp_sample_rate_hz": dsp_sample_rate,
        "baseline_repeatability_rmse_db": repeatability_rmse,
        "stock_restore_rmse_db": restore_rmse,
        "profiles": metrics,
        "alignment": diagnostics,
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    render_plot(
        args.output_dir / "frequency_response.png",
        frequencies,
        results,
        repeatability_centered,
        restore_delta,
    )

    report_lines = [
        "# ZX300A USB DAC 回环扫频测试报告",
        "",
        f"- 电脑侧采样率：{args.sample_rate} Hz；tone IIR 实际运行采样率：{dsp_sample_rate} Hz。",
        "",
        "## 测试指标",
        "",
        "| 配置 | 30 Hz-18 kHz RMSE | 1-6 kHz RMSE | 相关系数 | 关键频点理论 | 关键频点实测 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, values in metrics.items():
        report_lines.append(
            f"| {label} | {values['rmse_30_18000_db']:.2f} dB | "
            f"{values['rmse_1000_6000_db']:.2f} dB | "
            f"{values['correlation_30_18000']:.4f} | "
            f"{values['focus_frequency_hz']:.0f} Hz / {values['expected_at_focus_db']:+.2f} dB | "
            f"{values['focus_frequency_hz']:.0f} Hz / {values['measured_at_focus_db']:+.2f} dB |"
        )
    report_lines.extend(
        [
            "",
            f"- 两次基线的形状重复性 RMSE：{repeatability_rmse:.3f} dB。",
            (
                f"- 恢复基线后相对恢复前的 RMSE：{restore_rmse:.3f} dB。"
                if restore_rmse is not None
                else "- 本次未提供恢复基线后的复测。"
            ),
            "- 对每个自定义配置仅移除了一个全频段常量电平偏差；曲线形状没有做拟合或缩放。",
            "- 详细数据见 `frequency_response.csv`，自动对齐诊断见 `metrics.json`。",
            "",
            "![频响对比](frequency_response.png)",
            "",
        ]
    )
    (args.output_dir / "REPORT.md").write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    print(f"报告：{args.output_dir / 'REPORT.md'}")
    print(f"图：{args.output_dir / 'frequency_response.png'}")
    print(f"CSV：{csv_path}")


if __name__ == "__main__":
    main()
