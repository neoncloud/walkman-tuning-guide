#!/usr/bin/env python3
"""在 Windows 上通过指定的播放/录音设备执行同步对数扫频测量。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import chirp

try:
    import sounddevice as sd
except ImportError as exc:
    raise SystemExit(
        "缺少 sounddevice。请运行：python -m pip install sounddevice scipy numpy"
    ) from exc


def find_device(name: str, host_api: str, direction: str) -> tuple[int, dict, dict]:
    """按名称片段、Host API 和输入/输出方向查找唯一音频设备。"""
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()
    channel_key = "max_input_channels" if direction == "input" else "max_output_channels"
    name_lower = name.casefold()
    host_lower = host_api.casefold()
    matches: list[tuple[int, dict, dict]] = []

    for index, device in enumerate(devices):
        api = host_apis[device["hostapi"]]
        if (
            name_lower in device["name"].casefold()
            and host_lower in api["name"].casefold()
            and device[channel_key] > 0
        ):
            matches.append((index, dict(device), dict(api)))

    if not matches:
        available = [
            f"{index}: {device['name']} / {host_apis[device['hostapi']]['name']}"
            for index, device in enumerate(devices)
            if device[channel_key] > 0
        ]
        raise SystemExit(
            f"找不到{direction}设备 name~={name!r}, host_api~={host_api!r}。\n"
            + "\n".join(available)
        )
    if len(matches) > 1:
        desc = "\n".join(f"{index}: {device['name']} / {api['name']}" for index, device, api in matches)
        raise SystemExit(f"设备名称不唯一，请给出更具体的名称：\n{desc}")
    return matches[0]


def make_stimulus(
    sample_rate: int,
    start_hz: float,
    end_hz: float,
    sweep_seconds: float,
    repetitions: int,
    pre_silence: float,
    gap_seconds: float,
    post_silence: float,
    level_dbfs: float,
    fade_seconds: float,
) -> tuple[np.ndarray, list[int], int]:
    """生成带前后静音和重复段的双声道指数扫频。"""
    sweep_samples = int(round(sweep_seconds * sample_rate))
    pre_samples = int(round(pre_silence * sample_rate))
    gap_samples = int(round(gap_seconds * sample_rate))
    post_samples = int(round(post_silence * sample_rate))
    fade_samples = min(int(round(fade_seconds * sample_rate)), sweep_samples // 2)

    time_s = np.arange(sweep_samples, dtype=np.float64) / sample_rate
    sweep = chirp(
        time_s,
        f0=start_hz,
        f1=end_hz,
        t1=sweep_seconds,
        method="logarithmic",
        phi=-90.0,
    )
    if fade_samples:
        # sin^2 包络在端点的一阶导数为零，能减少扫频起止处的宽带瞬态。
        phase = np.linspace(0.0, math.pi / 2.0, fade_samples, endpoint=False)
        fade = np.sin(phase) ** 2
        sweep[:fade_samples] *= fade
        sweep[-fade_samples:] *= fade[::-1]
    sweep *= 10.0 ** (level_dbfs / 20.0)

    mono_parts: list[np.ndarray] = [np.zeros(pre_samples, dtype=np.float64)]
    sweep_starts: list[int] = []
    sample_cursor = pre_samples
    for repetition in range(repetitions):
        sweep_starts.append(sample_cursor)
        mono_parts.append(sweep)
        sample_cursor += sweep_samples
        if repetition != repetitions - 1:
            mono_parts.append(np.zeros(gap_samples, dtype=np.float64))
            sample_cursor += gap_samples
    mono_parts.append(np.zeros(post_samples, dtype=np.float64))

    mono = np.concatenate(mono_parts).astype(np.float32)
    return np.column_stack((mono, mono)), sweep_starts, sweep_samples


def make_periodic_noise_stimulus(
    sample_rate: int,
    start_hz: float,
    end_hz: float,
    period_samples: int,
    periods: int,
    pre_silence: float,
    post_silence: float,
    level_dbfs: float,
    seed: int,
) -> tuple[np.ndarray, int, int]:
    """生成确定性周期粉红噪声；所有 FFT 频点同时存在，可抵消录音端 AGC。"""
    frequencies = np.fft.rfftfreq(period_samples, d=1.0 / sample_rate)
    active = (frequencies >= start_hz) & (frequencies <= end_hz)
    active[0] = False
    rng = np.random.default_rng(seed)
    spectrum = np.zeros(len(frequencies), dtype=np.complex128)
    phases = rng.uniform(0.0, 2.0 * math.pi, np.count_nonzero(active))
    # 1/sqrt(f) 的幅度使每倍频程能量大致相等，兼顾低频与高频信噪比。
    spectrum[active] = np.exp(1j * phases) / np.sqrt(frequencies[active])
    period = np.fft.irfft(spectrum, n=period_samples)
    period /= max(float(np.max(np.abs(period))), 1e-30)
    period *= 10.0 ** (level_dbfs / 20.0)
    period = period.astype(np.float32)

    pre_samples = int(round(pre_silence * sample_rate))
    post_samples = int(round(post_silence * sample_rate))
    active_start = pre_samples
    mono = np.concatenate(
        (
            np.zeros(pre_samples, dtype=np.float32),
            np.tile(period, periods),
            np.zeros(post_samples, dtype=np.float32),
        )
    )
    return np.column_stack((mono, mono)), active_start, period_samples


def sha256_array(data: np.ndarray) -> str:
    return hashlib.sha256(data.tobytes(order="C")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--input-device", default="OsmoPocket3")
    parser.add_argument("--output-device", default="WALKMAN")
    parser.add_argument(
        "--host-api",
        default="Windows WDM-KS",
        help="默认使用 WDM-KS；该后端可让两个 USB 设备各自独占并同时工作",
    )
    parser.add_argument(
        "--shared",
        action="store_true",
        help="使用 WASAPI 共享模式；默认使用独占模式，避免其他播放内容混入",
    )
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument(
        "--input-sample-rate",
        type=int,
        help="录音设备采样率；默认沿用 --sample-rate",
    )
    parser.add_argument(
        "--output-sample-rate",
        type=int,
        help="播放设备采样率；默认沿用 --sample-rate",
    )
    parser.add_argument(
        "--output-channel",
        choices=("both", "left", "right"),
        default="both",
        help="播放到双声道、仅左声道或仅右声道",
    )
    parser.add_argument(
        "--signal",
        choices=("log-sweep", "periodic-noise"),
        default="log-sweep",
        help="periodic-noise 适合带自动增益的录音设备",
    )
    parser.add_argument("--start-hz", type=float, default=20.0)
    parser.add_argument("--end-hz", type=float, default=20000.0)
    parser.add_argument("--sweep-seconds", type=float, default=12.0)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--pre-silence", type=float, default=2.0)
    parser.add_argument("--gap-seconds", type=float, default=1.0)
    parser.add_argument("--post-silence", type=float, default=3.0)
    parser.add_argument("--fade-seconds", type=float, default=0.15)
    parser.add_argument("--level-dbfs", type=float, default=-30.0)
    parser.add_argument("--period-samples", type=int, default=65536)
    parser.add_argument("--periods", type=int, default=16)
    parser.add_argument("--settle-periods", type=int, default=2)
    parser.add_argument("--noise-seed", type=int, default=3778)
    args = parser.parse_args()

    input_sample_rate = args.input_sample_rate or args.sample_rate
    output_sample_rate = args.output_sample_rate or args.sample_rate
    if not (0.0 < args.start_hz < args.end_hz < output_sample_rate / 2.0):
        raise SystemExit("扫频范围必须满足 0 < start < end < Nyquist。")
    if args.repetitions < 1:
        raise SystemExit("--repetitions 必须至少为 1。")

    input_index, input_device, input_api = find_device(
        args.input_device, args.host_api, "input"
    )
    output_index, output_device, output_api = find_device(
        args.output_device, args.host_api, "output"
    )
    input_channels = min(2, int(input_device["max_input_channels"]))

    sd.check_input_settings(
        device=input_index,
        channels=input_channels,
        dtype="float32",
        samplerate=input_sample_rate,
    )
    sd.check_output_settings(
        device=output_index,
        channels=2,
        dtype="float32",
        samplerate=output_sample_rate,
    )

    if args.signal == "log-sweep":
        stimulus, output_sweep_starts, output_sweep_samples = make_stimulus(
            sample_rate=output_sample_rate,
            start_hz=args.start_hz,
            end_hz=args.end_hz,
            sweep_seconds=args.sweep_seconds,
            repetitions=args.repetitions,
            pre_silence=args.pre_silence,
            gap_seconds=args.gap_seconds,
            post_silence=args.post_silence,
            level_dbfs=args.level_dbfs,
            fade_seconds=args.fade_seconds,
        )
        output_active_start = output_sweep_starts[0]
        output_active_end = output_sweep_starts[-1] + output_sweep_samples
    else:
        if args.periods < 3 or not (0 <= args.settle_periods < args.periods):
            raise SystemExit("--periods 至少为 3，且 0 <= --settle-periods < --periods。")
        stimulus, output_active_start, output_period_samples = make_periodic_noise_stimulus(
            sample_rate=output_sample_rate,
            start_hz=args.start_hz,
            end_hz=args.end_hz,
            period_samples=args.period_samples,
            periods=args.periods,
            pre_silence=args.pre_silence,
            post_silence=args.post_silence,
            level_dbfs=args.level_dbfs,
            seed=args.noise_seed,
        )
        output_active_end = output_active_start + output_period_samples * args.periods

    if args.output_channel == "left":
        stimulus[:, 1] = 0.0
    elif args.output_channel == "right":
        stimulus[:, 0] = 0.0

    def output_to_input_sample(sample: int) -> int:
        return int(round(sample * input_sample_rate / output_sample_rate))

    active_start = output_to_input_sample(output_active_start)
    active_end = output_to_input_sample(output_active_end)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stimulus_path = args.output_dir / f"stimulus_{args.signal}_{output_sample_rate}hz.wav"
    recording_path = args.output_dir / f"{args.label}.wav"
    metadata_path = args.output_dir / f"{args.label}.json"
    if stimulus_path.exists():
        old_rate, old_stimulus = wavfile.read(stimulus_path)
        if old_rate != output_sample_rate or sha256_array(old_stimulus) != sha256_array(stimulus):
            raise SystemExit(
                f"{stimulus_path} 已存在但内容不同；请换一个输出目录，避免混用实验激励。"
            )
    else:
        wavfile.write(stimulus_path, output_sample_rate, stimulus)

    is_wasapi = "wasapi" in args.host_api.casefold()
    is_wdm_ks = "wdm-ks" in args.host_api.casefold()
    mode_text = (
        ("共享" if args.shared else "独占") + "模式"
        if is_wasapi
        else ("Kernel Streaming 独占模式" if is_wdm_ks else "标准模式")
    )
    print(
        f"播放：[{output_index}] {output_device['name']} / {output_api['name']}，"
        f"录音：[{input_index}] {input_device['name']} / {input_api['name']}"
    )
    print(
        f"开始采集 {len(stimulus) / output_sample_rate:.1f} 秒，"
        f"{args.start_hz:g}-{args.end_hz:g} Hz，{args.level_dbfs:g} dBFS，"
        f"信号={args.signal}，播放={output_sample_rate} Hz，录音={input_sample_rate} Hz，"
        f"{mode_text}。"
    )
    extra_settings = None
    if is_wasapi and not args.shared:
        wasapi = sd.WasapiSettings(exclusive=not args.shared)
        extra_settings = (wasapi, wasapi)

    # 两个 USB 设备有各自的硬件时钟，不能合并成一个 PortAudio 双工流。
    # 分别用回调流打开输入和输出：输入先启动，输出紧接着启动；后续分析
    # 通过扫频互相关测出实际启动延迟，不依赖软件启动时刻完全一致。
    input_settings, output_settings = (
        extra_settings if extra_settings is not None else (None, None)
    )
    recording_samples = int(
        round(len(stimulus) * input_sample_rate / output_sample_rate)
    )
    recording = np.zeros((recording_samples, input_channels), dtype=np.float32)
    input_cursor = 0
    output_cursor = 0
    stream_status: list[str] = []

    def input_callback(indata, frames, _time_info, status) -> None:
        nonlocal input_cursor
        if status:
            stream_status.append(f"input: {status}")
        count = min(frames, len(recording) - input_cursor)
        if count > 0:
            recording[input_cursor:input_cursor + count] = indata[:count]
            input_cursor += count
        if input_cursor >= len(recording):
            raise sd.CallbackStop

    def output_callback(outdata, frames, _time_info, status) -> None:
        nonlocal output_cursor
        if status:
            stream_status.append(f"output: {status}")
        outdata.fill(0.0)
        count = min(frames, len(stimulus) - output_cursor)
        if count > 0:
            outdata[:count] = stimulus[output_cursor:output_cursor + count]
            output_cursor += count
        if output_cursor >= len(stimulus):
            raise sd.CallbackStop

    input_finished = threading.Event()
    output_finished = threading.Event()
    input_stream = sd.InputStream(
        samplerate=input_sample_rate,
        channels=input_channels,
        dtype="float32",
        device=input_index,
        latency="high",
        extra_settings=input_settings,
        callback=input_callback,
        finished_callback=input_finished.set,
    )
    output_stream = sd.OutputStream(
        samplerate=output_sample_rate,
        channels=2,
        dtype="float32",
        device=output_index,
        latency="high",
        extra_settings=output_settings,
        callback=output_callback,
        finished_callback=output_finished.set,
    )
    timeout = len(stimulus) / output_sample_rate + 5.0
    try:
        input_stream.start()
        output_stream.start()
        if not output_finished.wait(timeout):
            raise RuntimeError("播放流没有按时结束。")
        if not input_finished.wait(timeout):
            raise RuntimeError("录音流没有按时结束。")
    finally:
        input_stream.stop(ignore_errors=True)
        output_stream.stop(ignore_errors=True)
        input_stream.close(ignore_errors=True)
        output_stream.close(ignore_errors=True)
    if stream_status:
        raise RuntimeError("音频流异常：" + "; ".join(stream_status))
    wavfile.write(recording_path, input_sample_rate, recording.astype(np.float32))

    analysis_start = max(0, active_start - input_sample_rate // 2)
    analysis_end = min(len(recording), active_end + input_sample_rate // 2)
    active = recording[analysis_start:analysis_end]
    rms = np.sqrt(np.mean(np.square(active.astype(np.float64)), axis=0))
    peak = np.max(np.abs(active), axis=0)
    clipping = np.sum(np.abs(active) >= 0.999, axis=0)
    selected_channel = int(np.argmax(rms))

    metadata = {
        "schema": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "label": args.label,
        "sample_rate": input_sample_rate,
        "input_sample_rate": input_sample_rate,
        "output_sample_rate": output_sample_rate,
        "output_channel": args.output_channel,
        "signal_type": args.signal,
        "start_hz": args.start_hz,
        "end_hz": args.end_hz,
        "level_dbfs": args.level_dbfs,
        "stimulus_path": stimulus_path.name,
        "stimulus_sha256": sha256_array(stimulus),
        "recording_path": recording_path.name,
        "input_device_index": input_index,
        "input_device": input_device,
        "input_host_api": input_api["name"],
        "output_device_index": output_index,
        "output_device": output_device,
        "output_host_api": output_api["name"],
        "audio_mode": mode_text,
        "recorded_channels": input_channels,
        "selected_channel_zero_based": selected_channel,
        "channel_rms_dbfs": [
            float(20.0 * np.log10(max(value, 1e-15))) for value in rms
        ],
        "channel_peak_dbfs": [
            float(20.0 * np.log10(max(value, 1e-15))) for value in peak
        ],
        "channel_clipped_samples": [int(value) for value in clipping],
    }
    if args.signal == "log-sweep":
        sweep_starts = [
            output_to_input_sample(value) for value in output_sweep_starts
        ]
        sweep_samples = output_to_input_sample(output_sweep_samples)
        metadata.update(
            {
                "sweep_seconds": args.sweep_seconds,
                "sweep_starts": sweep_starts,
                "sweep_samples": sweep_samples,
                "output_sweep_starts": output_sweep_starts,
                "output_sweep_samples": output_sweep_samples,
                "repetitions": args.repetitions,
            }
        )
    else:
        period_samples = output_to_input_sample(output_period_samples)
        metadata.update(
            {
                "active_start_sample": active_start,
                "period_samples": period_samples,
                "output_active_start_sample": output_active_start,
                "output_period_samples": output_period_samples,
                "periods": args.periods,
                "settle_periods": args.settle_periods,
                "noise_seed": args.noise_seed,
            }
        )
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"录音：{recording_path}")
    print(
        "通道统计："
        + ", ".join(
            f"ch{index + 1} RMS={metadata['channel_rms_dbfs'][index]:.2f} dBFS "
            f"peak={metadata['channel_peak_dbfs'][index]:.2f} dBFS "
            f"clip={metadata['channel_clipped_samples'][index]}"
            for index in range(input_channels)
        )
    )
    print(f"分析将使用 ch{selected_channel + 1}。")
    if any(clipping):
        raise SystemExit("录音发生削波；请降低播放器音量或 --level-dbfs 后重测。")


if __name__ == "__main__":
    main()
