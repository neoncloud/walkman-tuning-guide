#!/usr/bin/env python3
"""比较 DSEE 开启/关闭的多采样率回环，并合并定向复测结果。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


def read_metrics(path: Path) -> dict:
    """读取并检查采样率分析结果。"""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if "rates" not in data:
        raise ValueError(f"{path}: 缺少 rates")
    return data


def index_rates(metrics: dict) -> dict[int, dict]:
    """按 USB 输入采样率建立索引。"""
    return {
        int(item["input_sample_rate_hz"]): item
        for item in metrics["rates"]
    }


def compact_metrics(item: dict) -> dict:
    """只保留跨实验比较需要的稳定指标。"""
    return {
        "tone_effect_active": bool(item["effect_active"]),
        "expected_tone_dsp_sample_rate_hz": float(
            item["expected_tone_dsp_sample_rate_hz"]
        ),
        "fitted_tone_dsp_sample_rate_hz": float(
            item["fitted_tone_dsp_sample_rate_hz"]
        ),
        "clock_error_percent": float(item["clock_error_percent"]),
        "common_probe_rmse_db": float(
            item["common_probe_rmse_at_fitted_clock_db"]
        ),
        "common_probe_correlation": float(item["common_probe_correlation"]),
        "common_probe_peak_frequency_hz": float(
            item["common_probe_peak_frequency_hz"]
        ),
        "common_probe_peak_db": float(item["common_probe_peak_db"]),
        "captured_path_half_match": item["captured_path_half_match"],
        "captured_path_half_rmse_db": float(
            item["captured_path_half_rmse_db"]
        ),
    }


def portable_path(path: Path | None) -> str | None:
    """优先把来源文件记录为相对仓库路径，避免归档本机绝对路径。"""
    if path is None:
        return None
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(resolved)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsee-on-metrics", type=Path, required=True)
    parser.add_argument("--dsee-off-metrics", type=Path, required=True)
    parser.add_argument(
        "--dsee-off-repeat-metrics",
        type=Path,
        help="可选；其中存在的采样率会覆盖 DSEE-off 首轮结果",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    dsee_on = index_rates(read_metrics(args.dsee_on_metrics))
    dsee_off = index_rates(read_metrics(args.dsee_off_metrics))
    repeat: dict[int, dict] = {}
    if args.dsee_off_repeat_metrics:
        repeat = index_rates(read_metrics(args.dsee_off_repeat_metrics))

    rates = sorted(dsee_off)
    missing_on = sorted(set(rates) - set(dsee_on))
    if missing_on:
        raise SystemExit(f"DSEE-on 数据缺少采样率：{missing_on}")

    results: list[dict] = []
    for rate in rates:
        off_source = "定向复测" if rate in repeat else "完整矩阵"
        off_item = repeat.get(rate, dsee_off[rate])
        on_result = compact_metrics(dsee_on[rate])
        off_result = compact_metrics(off_item)
        results.append(
            {
                "input_sample_rate_hz": rate,
                "dsee_on": on_result,
                "dsee_off": off_result,
                "dsee_off_source": off_source,
                "fitted_clock_change_off_minus_on_hz": (
                    off_result["fitted_tone_dsp_sample_rate_hz"]
                    - on_result["fitted_tone_dsp_sample_rate_hz"]
                ),
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = {
        "dsee_on_metrics": portable_path(args.dsee_on_metrics),
        "dsee_off_metrics": portable_path(args.dsee_off_metrics),
        "dsee_off_repeat_metrics": portable_path(
            args.dsee_off_repeat_metrics
        ),
        "rates": results,
    }
    (args.output_dir / "comparison.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    positions = np.arange(len(rates))
    on_error = [item["dsee_on"]["clock_error_percent"] for item in results]
    off_error = [item["dsee_off"]["clock_error_percent"] for item in results]
    on_rmse = [item["dsee_on"]["common_probe_rmse_db"] for item in results]
    off_rmse = [item["dsee_off"]["common_probe_rmse_db"] for item in results]

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 7.2), sharex=True)
    width = 0.38
    axes[0].bar(
        positions - width / 2,
        on_error,
        width,
        label="DSEE 开启轮次（未复测异常点）",
        color="#5675A3",
    )
    axes[0].bar(
        positions + width / 2,
        off_error,
        width,
        label="DSEE 关闭轮次（含复测）",
        color="#D16A4A",
    )
    axes[0].axhline(0.0, color="0.25", linewidth=0.9)
    axes[0].set_ylabel("相对固定 family 时钟误差 / %")
    axes[0].grid(True, axis="y", alpha=0.25)
    axes[0].legend()

    axes[1].bar(
        positions - width / 2,
        on_rmse,
        width,
        label="DSEE 开启轮次（未复测异常点）",
        color="#5675A3",
    )
    axes[1].bar(
        positions + width / 2,
        off_rmse,
        width,
        label="DSEE 关闭轮次（含复测）",
        color="#D16A4A",
    )
    axes[1].set_ylabel("共同探针拟合 RMSE / dB")
    axes[1].set_xlabel("USB 输入采样率 / Hz")
    axes[1].set_xticks(positions, [str(rate) for rate in rates])
    axes[1].grid(True, axis="y", alpha=0.25)
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(args.output_dir / "dsee_comparison.png", dpi=170)
    plt.close(fig)

    max_off_clock_error = max(
        abs(item["dsee_off"]["clock_error_percent"]) for item in results
    )
    max_off_rmse = max(
        item["dsee_off"]["common_probe_rmse_db"] for item in results
    )
    all_off_active = all(
        item["dsee_off"]["tone_effect_active"] for item in results
    )
    off_halves = sorted(
        {
            item["dsee_off"]["captured_path_half_match"]
            for item in results
        }
    )
    report = [
        "# ZX300A USB DAC DSEE 开关采样率对比",
        "",
        "## 结论",
        "",
        (
            f"- DSEE 关闭后八档 tone table 均{'生效' if all_off_active else '未全部生效'}；"
            f"固定 family 时钟最大绝对误差为 {max_off_clock_error:.3f}%。"
        ),
        f"- DSEE 关闭结果的共同探针最大拟合 RMSE 为 {max_off_rmse:.3f} dB。",
        f"- DSEE 关闭后当前采集通路匹配的 half 集合为 `{off_halves}`。",
        "- 两轮都支持 44.1 kHz 家族约 176.4 kHz、48 kHz 家族约 192 kHz 的固定时钟模型。",
        "- DSEE 开启轮次与关闭轮次都出现过单次采集异常；关闭轮次用 16 周期定向复测替换了 48/352.8 kHz 异常点。",
        "- 因此不能把两轮个别拟合差值解释成 DSEE 改变了 tone-DSP 时钟。",
        "- OsmoPocket3 存在动态增益，不能用跨轮次绝对录音电平定量判断 DSEE 增益。",
        "",
        "| USB 输入 | DSEE 开启拟合 Fs | DSEE 关闭拟合 Fs | 关闭误差 | 关闭 RMSE | 关闭数据来源 | half |",
        "|---:|---:|---:|---:|---:|:---:|:---:|",
    ]
    for item in results:
        on = item["dsee_on"]
        off = item["dsee_off"]
        report.append(
            f"| {item['input_sample_rate_hz']} Hz | "
            f"{on['fitted_tone_dsp_sample_rate_hz']:.0f} Hz | "
            f"{off['fitted_tone_dsp_sample_rate_hz']:.0f} Hz | "
            f"{off['clock_error_percent']:+.3f}% | "
            f"{off['common_probe_rmse_db']:.3f} dB | "
            f"{item['dsee_off_source']} | "
            f"{off['captured_path_half_match']} |"
        )
    report.extend(
        [
            "",
            "![DSEE 开关对比](dsee_comparison.png)",
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
