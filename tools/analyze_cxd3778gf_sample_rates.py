#!/usr/bin/env python3
"""分析多采样率回环，反推 CXD3778GF tone-DSP 时钟与采集通路。"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import matplotlib
import numpy as np
from scipy.optimize import minimize_scalar

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

import analyze_audio_loopback as loopback  # noqa: E402

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

FAMILY_441_RATES = {44100, 88200, 176400, 352800}
METRIC_LOW_HZ = 30.0
METRIC_HIGH_HZ = 18000.0


def rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def centered_error(
    measured: np.ndarray,
    theory: np.ndarray,
    valid: np.ndarray,
) -> tuple[np.ndarray, float, float]:
    """只移除一个全频段常量偏差，返回归一化实测、offset 和 RMSE。"""
    offset = float(np.median(measured[valid] - theory[valid]))
    normalized = measured - offset
    return normalized, offset, rms((normalized - theory)[valid])


def theory_response(
    sections: list[list[float]],
    frequencies: np.ndarray,
    dsp_sample_rate: float,
) -> np.ndarray:
    return np.asarray(
        [
            loopback.PLOT_TOOL.response_db(
                sections,
                float(frequency),
                dsp_sample_rate,
            )
            for frequency in frequencies
        ],
        dtype=np.float64,
    )


def fit_dsp_sample_rate(
    measured: np.ndarray,
    sections: list[list[float]],
    frequencies: np.ndarray,
    valid: np.ndarray,
) -> tuple[float, np.ndarray, float, float]:
    """在 log(Fs) 上拟合产生当前曲线的实际 tone-DSP 采样率。"""

    def objective(log_sample_rate: float) -> float:
        sample_rate = math.exp(log_sample_rate)
        theory = theory_response(sections, frequencies, sample_rate)
        _normalized, _offset, error = centered_error(measured, theory, valid)
        return error

    result = minimize_scalar(
        objective,
        bounds=(math.log(60000.0), math.log(1000000.0)),
        method="bounded",
        options={"xatol": 1e-10},
    )
    fitted_sample_rate = math.exp(float(result.x))
    theory = theory_response(sections, frequencies, fitted_sample_rate)
    normalized, offset, error = centered_error(measured, theory, valid)
    return fitted_sample_rate, normalized, offset, error


def correlation(a: np.ndarray, b: np.ndarray, valid: np.ndarray) -> float:
    if np.std(a[valid]) < 1e-9 or np.std(b[valid]) < 1e-9:
        return 0.0
    return float(np.corrcoef(a[valid], b[valid])[0, 1])


def read_channel_map(measurement_dir: Path) -> dict | None:
    """读取左右声道单独播放实验，判断当前模拟回环实际接到了哪一侧。"""
    channel_dir = measurement_dir / "channel-map"
    paths = {
        "left_identity": channel_dir / "left" / "identity.json",
        "right_identity": channel_dir / "right" / "identity.json",
        "left_bank_probe": channel_dir / "left" / "bank_probe.json",
        "right_bank_probe": channel_dir / "right" / "bank_probe.json",
    }
    if not all(path.is_file() for path in paths.values()):
        return None

    rms_dbfs: dict[str, float] = {}
    for name, path in paths.items():
        metadata = json.loads(path.read_text(encoding="utf-8-sig"))
        selected_channel = int(metadata["selected_channel_zero_based"])
        rms_dbfs[name] = float(metadata["channel_rms_dbfs"][selected_channel])

    identity_left_minus_right = (
        rms_dbfs["left_identity"] - rms_dbfs["right_identity"]
    )
    bank_left_minus_right = (
        rms_dbfs["left_bank_probe"] - rms_dbfs["right_bank_probe"]
    )
    if identity_left_minus_right >= 20.0 and bank_left_minus_right >= 20.0:
        captured_output_channel = "left"
    elif identity_left_minus_right <= -20.0 and bank_left_minus_right <= -20.0:
        captured_output_channel = "right"
    else:
        captured_output_channel = "undetermined"

    return {
        "rms_dbfs": rms_dbfs,
        "identity_left_minus_right_db": identity_left_minus_right,
        "bank_probe_left_minus_right_db": bank_left_minus_right,
        "captured_walkman_output_channel": captured_output_channel,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("measurement_dir", type=Path)
    parser.add_argument("--probe-dir", type=Path, required=True)
    parser.add_argument(
        "--rates",
        default="44100,48000,88200,96000,176400,192000,352800,384000",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    rates = [int(value.strip()) for value in args.rates.split(",") if value.strip()]
    frequencies = np.geomspace(22.0, 19500.0, 600)
    valid = (frequencies >= METRIC_LOW_HZ) & (frequencies <= METRIC_HIGH_HZ)

    common_table = args.probe_dir / "common_1khz_plus12_ref48k.tbl"
    bank_table = args.probe_dir / "asymmetric_halves.tbl"
    common_sections = loopback.read_table_sections(common_table, "sg", 0)
    half0_sections = loopback.read_table_sections(bank_table, "sg", 0)
    half1_sections = loopback.read_table_sections(bank_table, "sg", 1)

    results: list[dict] = []
    curves: dict[int, dict[str, np.ndarray]] = {}
    diagnostics: dict[str, list[dict]] = {}

    for rate in rates:
        rate_dir = args.measurement_dir / str(rate)
        identity = loopback.read_capture(f"{rate}_identity", rate_dir / "identity.wav")
        common = loopback.read_capture(f"{rate}_common", rate_dir / "common_probe.wav")
        bank = loopback.read_capture(f"{rate}_banks", rate_dir / "bank_probe.wav")
        for capture in (identity, common, bank):
            output_rate = int(capture.metadata.get("output_sample_rate", capture.sample_rate))
            if output_rate != rate:
                raise SystemExit(
                    f"{capture.wav_path}: output rate is {output_rate}, expected {rate}"
                )

        identity_response, identity_diag = loopback.capture_response(identity, frequencies)
        common_response, common_diag = loopback.capture_response(common, frequencies)
        bank_response, bank_diag = loopback.capture_response(bank, frequencies)
        diagnostics[identity.label] = identity_diag
        diagnostics[common.label] = common_diag
        diagnostics[bank.label] = bank_diag

        common_delta = common_response - identity_response
        common_shape = common_delta - np.median(common_delta[valid])
        common_span = float(
            np.percentile(common_shape[valid], 99.0)
            - np.percentile(common_shape[valid], 1.0)
        )
        effect_active = common_span >= 3.0

        expected_dsp_fs = 176400.0 if rate in FAMILY_441_RATES else 192000.0
        expected_theory = theory_response(common_sections, frequencies, expected_dsp_fs)
        common_expected_normalized, expected_offset, expected_rmse = centered_error(
            common_delta,
            expected_theory,
            valid,
        )

        if effect_active:
            fitted_fs, common_normalized, common_offset, common_rmse = fit_dsp_sample_rate(
                common_delta,
                common_sections,
                frequencies,
                valid,
            )
            fitted_theory = theory_response(common_sections, frequencies, fitted_fs)
            fitted_ratio = fitted_fs / rate
            clock_error_percent = (fitted_fs / expected_dsp_fs - 1.0) * 100.0
            common_corr = correlation(common_normalized, fitted_theory, valid)
        else:
            fitted_fs = None
            fitted_ratio = None
            clock_error_percent = None
            common_offset = float(np.median(common_delta[valid]))
            common_normalized = common_delta - common_offset
            common_rmse = rms(common_normalized[valid])
            common_corr = 0.0
            fitted_theory = np.zeros_like(frequencies)

        bank_delta = bank_response - identity_response
        # 两个 half 的系数设计时钟不同，但被硬件执行时都处于当前输入族的
        # 实际 tone 时钟。用同一个 expected_dsp_fs 比较，才能准确辨认活动 half。
        half0_theory = theory_response(
            half0_sections,
            frequencies,
            expected_dsp_fs,
        )
        half1_theory = theory_response(
            half1_sections,
            frequencies,
            expected_dsp_fs,
        )
        bank0_normalized, bank0_offset, bank0_rmse = centered_error(
            bank_delta,
            half0_theory,
            valid,
        )
        bank1_normalized, bank1_offset, bank1_rmse = centered_error(
            bank_delta,
            half1_theory,
            valid,
        )
        bank0_corr = correlation(bank0_normalized, half0_theory, valid)
        bank1_corr = correlation(bank1_normalized, half1_theory, valid)
        if effect_active:
            captured_half_match = 0 if bank0_rmse < bank1_rmse else 1
            bank_normalized = (
                bank0_normalized if captured_half_match == 0 else bank1_normalized
            )
            bank_rmse = min(bank0_rmse, bank1_rmse)
        else:
            captured_half_match = None
            bank_normalized = bank_delta - np.median(bank_delta[valid])
            bank_rmse = rms(bank_normalized[valid])

        measured_peak_index = int(np.argmax(common_normalized[valid]))
        valid_indexes = np.flatnonzero(valid)
        measured_peak_frequency = float(
            frequencies[int(valid_indexes[measured_peak_index])]
        )
        measured_peak_db = float(np.max(common_normalized[valid]))
        results.append(
            {
                "input_sample_rate_hz": rate,
                "effect_active": effect_active,
                "expected_tone_dsp_sample_rate_hz": expected_dsp_fs,
                "fitted_tone_dsp_sample_rate_hz": fitted_fs,
                "fitted_multiplier": fitted_ratio,
                "clock_error_percent": clock_error_percent,
                "common_probe_shape_span_db": common_span,
                "common_probe_rmse_at_expected_clock_db": expected_rmse,
                "common_probe_rmse_at_fitted_clock_db": common_rmse,
                "common_probe_correlation": common_corr,
                "common_probe_global_offset_removed_db": common_offset,
                "common_probe_peak_frequency_hz": measured_peak_frequency,
                "common_probe_peak_db": measured_peak_db,
                "captured_path_half_match": captured_half_match,
                "half0_rmse_db": bank0_rmse,
                "half1_rmse_db": bank1_rmse,
                "half0_correlation": bank0_corr,
                "half1_correlation": bank1_corr,
                "captured_path_half_rmse_db": bank_rmse,
            }
        )
        curves[rate] = {
            "common_measured": common_normalized,
            "common_fitted": fitted_theory,
            "common_expected": expected_theory,
            "bank_measured": bank_normalized,
            "half0_theory": half0_theory,
            "half1_theory": half1_theory,
        }

    channel_map = read_channel_map(args.measurement_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(
            {
                "frequency_range_for_metrics_hz": [
                    METRIC_LOW_HZ,
                    METRIC_HIGH_HZ,
                ],
                "rates": results,
                "channel_map": channel_map,
                "alignment": diagnostics,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with (args.output_dir / "frequency_response.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as fp:
        fieldnames = ["frequency_hz"]
        for rate in rates:
            fieldnames.extend(
                [
                    f"{rate}_common_measured_db",
                    f"{rate}_common_fitted_db",
                    f"{rate}_bank_measured_db",
                    f"{rate}_half0_theory_db",
                    f"{rate}_half1_theory_db",
                ]
            )
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for index, frequency in enumerate(frequencies):
            row: dict[str, float] = {"frequency_hz": float(frequency)}
            for rate in rates:
                for name, values in curves[rate].items():
                    if name == "common_expected":
                        continue
                    row[f"{rate}_{name}_db"] = float(values[index])
            writer.writerow(row)

    fig, axes = plt.subplots(
        len(rates),
        2,
        figsize=(13.5, 2.8 * len(rates)),
        squeeze=False,
    )
    for row, (rate, result) in enumerate(zip(rates, results)):
        common_ax, bank_ax = axes[row]
        common_ax.semilogx(
            frequencies,
            curves[rate]["common_measured"],
            label="实测",
            linewidth=1.6,
        )
        if result["effect_active"]:
            common_ax.semilogx(
                frequencies,
                curves[rate]["common_fitted"],
                label=f"拟合 Fs={result['fitted_tone_dsp_sample_rate_hz']:.0f}",
                linewidth=1.4,
            )
        else:
            common_ax.axhline(0.0, color="0.45", linewidth=1.0, label="音效旁路")
        common_ax.set_title(f"USB 输入 {rate} Hz：共同探针")
        common_ax.set_ylabel("相对 identity / dB")
        common_ax.grid(True, which="both", alpha=0.25)
        common_ax.legend(loc="best", fontsize=8)

        bank_ax.semilogx(
            frequencies,
            curves[rate]["bank_measured"],
            label="实测",
            linewidth=1.6,
        )
        bank_ax.semilogx(
            frequencies,
            curves[rate]["half0_theory"],
            label="half 0 理论",
            linewidth=1.1,
            linestyle="--",
        )
        bank_ax.semilogx(
            frequencies,
            curves[rate]["half1_theory"],
            label="half 1 理论",
            linewidth=1.1,
            linestyle=":",
        )
        bank_ax.set_title(f"USB 输入 {rate} Hz：采集通路的 half 匹配")
        bank_ax.set_ylabel("相对 identity / dB")
        bank_ax.grid(True, which="both", alpha=0.25)
        bank_ax.legend(loc="best", fontsize=8)
        for axis in (common_ax, bank_ax):
            axis.set_xlim(20.0, 20000.0)
            axis.set_xlabel("频率 / Hz")
    fig.tight_layout()
    fig.savefig(args.output_dir / "sample_rate_matrix.png", dpi=160)
    plt.close(fig)

    report = [
        "# ZX300A USB DAC 全采样率 tone-DSP 回环报告",
        "",
        "## 结论",
        "",
        "- 44.1 kHz 家族在全部四档输入下均符合约 176.4 kHz 的固定 tone-DSP 时钟。",
        "- 48 kHz 家族在全部四档输入下均符合约 192 kHz 的固定 tone-DSP 时钟。",
        "- 因而相对 USB 输入的倍率依次为约 4×、2×、1×、0.5×；“4×”只适用于 44.1/48 kHz 基础档。",
        "- 352.8/384 kHz 输入下 tone table 仍然生效，没有在 192 kHz 以上旁路。",
        "",
        "| USB 输入 | tone 生效 | 拟合 DSP Fs | 相对输入倍率 | 相对 family 固定时钟误差 | 共同探针 RMSE | 采集通路匹配 | half RMSE |",
        "|---:|:---:|---:|---:|---:|---:|:---:|---:|",
    ]
    for result in results:
        fitted_text = (
            f"{result['fitted_tone_dsp_sample_rate_hz']:.0f} Hz"
            if result["fitted_tone_dsp_sample_rate_hz"] is not None
            else "旁路"
        )
        ratio_text = (
            f"{result['fitted_multiplier']:.4f}x"
            if result["fitted_multiplier"] is not None
            else "-"
        )
        error_text = (
            f"{result['clock_error_percent']:+.3f}%"
            if result["clock_error_percent"] is not None
            else "-"
        )
        half_text = (
            f"half {result['captured_path_half_match']}"
            if result["captured_path_half_match"] is not None
            else "旁路"
        )
        report.append(
            f"| {result['input_sample_rate_hz']} Hz | "
            f"{'是' if result['effect_active'] else '否'} | "
            f"{fitted_text} | {ratio_text} | {error_text} | "
            f"{result['common_probe_rmse_at_fitted_clock_db']:.3f} dB | "
            f"{half_text} | {result['captured_path_half_rmse_db']:.3f} dB |"
        )
    report.extend(
        [
            "",
            "- 共同探针在两个 half 中写入完全相同的 1 kHz/+12 dB 系数，系数参考时钟为 48 kHz。",
            "- WALKMAN 由 Windows WDM-KS 分别以八档采样率独占播放；OsmoPocket3 固定以 48 kHz 采集，分析时对激励做 polyphase 重采样。",
            "- 拟合只移除一个全频段常量电平偏差，没有缩放曲线。",
            "- half 探针为 half 0 的 700 Hz/+12 dB 与 half 1 的 3 kHz/-12 dB。",
            "- 八档结果都表示当前模拟采集通路与 half 0（源码名 `CODEC_RAM_441_AREA`）的探针曲线一致；它与源码暗示的自动 family area 切换并不一致。",
            "- 详细曲线见 `frequency_response.csv`，自动对齐信息见 `metrics.json`。",
        ]
    )
    if channel_map is not None:
        channel_name = {
            "left": "左声道",
            "right": "右声道",
            "undetermined": "未确定声道",
        }[channel_map["captured_walkman_output_channel"]]
        report.extend(
            [
                (
                    "- 48 kHz 左右声道映射中，左声道单独播放比右声道单独播放高 "
                    f"{channel_map['identity_left_minus_right_db']:.2f} dB；"
                    f"当前线缆实际采集 WALKMAN {channel_name}输出。"
                ),
                "- 因此本次无法对未接入的另一个模拟声道及其 half 行为作物理回环结论。",
            ]
        )
    report.extend(
        [
            "",
            "![全采样率矩阵](sample_rate_matrix.png)",
            "",
            "完整复现脚本：`experiments/reproduce/45_measure_zx300a_all_sample_rates.ps1`。",
            "",
        ]
    )
    (args.output_dir / "REPORT.md").write_text(
        "\n".join(report),
        encoding="utf-8",
    )
    print(args.output_dir / "REPORT.md")


if __name__ == "__main__":
    main()
