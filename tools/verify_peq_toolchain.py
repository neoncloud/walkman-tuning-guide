#!/usr/bin/env python3
"""Run regression checks for the CXD3778GF PEQ helper toolchain."""

from __future__ import annotations

import cmath
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DUMP = ROOT / "device-dumps" / "a50-10459245524948"

sys.path.insert(0, str(TOOLS))
import analyze_peq_measurement as measurement  # noqa: E402
import autoeq_to_cxd3778gf_peq as peq  # noqa: E402
import plot_cxd3778gf_tct_response as plotter  # noqa: E402
import cxd3778gf_tct_tool as tct  # noqa: E402


def note(text: str) -> None:
    print(f"[ok] {text}")


def fail(text: str) -> None:
    raise SystemExit(f"[fail] {text}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, **kwargs)


def response_db(sections: list[list[float]], freq: float, fs: float) -> float:
    z1 = cmath.exp(-2j * math.pi * freq / fs)
    z2 = z1 * z1
    h = 1 + 0j
    for b0, b1, b2, neg_a1, neg_a2 in sections:
        h *= (b0 + b1 * z1 + b2 * z2) / (1 - neg_a1 * z1 - neg_a2 * z2)
    return 20.0 * math.log10(abs(h))


def ideal_sections(filters: list[peq.Filter], fs: float, preamp_db: float) -> list[list[float]]:
    sections = [peq.coefficients(f, fs) for f in filters]
    sections.extend(peq.identity_sections()[len(sections):])
    gain = 10 ** (preamp_db / 20.0)
    for idx in range(3):
        sections[0][idx] *= gain
    return sections


def check_empty_matches_sg(tmp: Path) -> None:
    stock_sg = DUMP / "proc_tct_sg.bin"
    if not stock_sg.exists():
        note("private A50 stock tct_sg dump is missing; skipping stock empty-table comparison")
        return
    empty_txt = tmp / "empty.txt"
    empty_bin = tmp / "empty.bin"
    empty_txt.write_text("")
    run([str(TOOLS / "autoeq_to_cxd3778gf_peq.py"), "--body-only", str(empty_txt), str(empty_bin)])
    if empty_bin.read_bytes() != stock_sg.read_bytes():
        fail("empty AutoEq body no longer matches stock tct_sg")
    note("empty AutoEq output matches stock tct_sg")


def check_sample_quantization(tmp: Path) -> None:
    sample_txt = ROOT / "samples" / "sample-autoeq.txt"
    sample_blob = tmp / "sample.proc"
    run([str(TOOLS / "autoeq_to_cxd3778gf_peq.py"), str(sample_txt), str(sample_blob)])
    if sample_blob.stat().st_size != 328:
        fail(f"sample blob size is {sample_blob.stat().st_size}, expected 328")
    preamp, filters = peq.parse_autoeq(sample_txt.read_text())
    for half, fs in ((0, peq.DEFAULT_TONE_FS_441), (1, peq.DEFAULT_TONE_FS_48)):
        encoded = plotter.decode_sections(sample_blob, half)
        ideal = ideal_sections(filters, fs, preamp)
        max_coeff_error = max(abs(a - b) for aa, bb in zip(encoded, ideal) for a, b in zip(aa, bb))
        freqs = peq.logspace(20.0, 20000.0, 256)
        max_response_error = max(abs(response_db(encoded, f, fs) - response_db(ideal, f, fs)) for f in freqs)
        if max_coeff_error > 1e-9 or max_response_error > 1e-5:
            fail(
                f"sample quantization too large for half={half}: "
                f"coeff={max_coeff_error:.3e} response={max_response_error:.3e}dB"
            )
    note("sample PEQ Q37 quantization is below tolerance")


def check_q37_preamp_distribution(tmp: Path) -> None:
    """验证高增益 shelf 可通过等价 preamp 分配编码，且级联频响不变。"""
    evo = tmp / "evo.txt"
    blob = tmp / "evo.proc"
    evo.write_text(
        "\n".join(
            (
                "Preamp: -8.74 dB",
                "Filter 1: ON LSC Fc 105.0 Hz Gain 1.0 dB Q 0.70",
                "Filter 2: ON PK Fc 213.8 Hz Gain -2.1 dB Q 1.42",
                "Filter 3: ON PK Fc 1787.5 Hz Gain -4.0 dB Q 1.35",
                "Filter 4: ON PK Fc 8921.5 Hz Gain 2.8 dB Q 0.18",
                "Filter 5: ON HSC Fc 20000.0 Hz Gain 16.3 dB Q 0.70",
            )
        )
        + "\n"
    )
    run([str(TOOLS / "autoeq_to_cxd3778gf_peq.py"), str(evo), str(blob)])
    requested_preamp, filters = peq.parse_autoeq(evo.read_text())
    preamp = peq.limit_preamp_for_headroom(
        filters,
        requested_preamp,
        peq.DEFAULT_TONE_FS_441,
        peq.DEFAULT_TONE_FS_48,
        "first",
        5,
    )
    if not preamp < requested_preamp:
        fail("EVO fixture should require additional headroom at the 4x tone-DSP clocks")
    freqs = peq.logspace(20.0, 20000.0, 512)
    for half, fs in ((0, peq.DEFAULT_TONE_FS_441), (1, peq.DEFAULT_TONE_FS_48)):
        encoded = plotter.decode_sections(blob, half)
        expected = [
            value + preamp
            for value in peq.response_db_for_filters(filters, freqs, fs)
        ]
        actual = [response_db(encoded, freq, fs) for freq in freqs]
        max_error = max(abs(got - want) for got, want in zip(actual, expected))
        if max_error > 1e-5:
            fail(f"distributed-preamp response error is {max_error:.3e} dB for half={half}")
        if max(actual) > 1e-5:
            fail(f"automatic headroom left a positive peak of {max(actual):.6f} dB for half={half}")
    note("preamp distribution keeps high-gain shelves inside Q37 without changing response")


def strategy_error(filters: list[peq.Filter], selected: list[peq.Filter]) -> tuple[float, float]:
    freqs = peq.logspace(20.0, 20000.0, 512)
    target = peq.response_db_for_filters(filters, freqs, peq.DEFAULT_TONE_FS_441)
    got = peq.response_db_for_filters(selected, freqs, peq.DEFAULT_TONE_FS_441)
    diffs = [a - b for a, b in zip(got, target)]
    rms = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    return rms, max(abs(d) for d in diffs)


def check_filter_strategies() -> None:
    text = (ROOT / "samples" / "filter-strategy" / "autoeq-8filters.txt").read_text()
    _preamp, filters = peq.parse_autoeq(text)
    expected = {
        "first": "1+2+3+4+5",
        "largest": "2+5+6+7+8",
        "wide": "2+5+6+7+8",
        "greedy": "1+4+5+6+8",
        "best": "2+3+6+7+8",
    }
    errors = {}
    for strategy, selected_ids in expected.items():
        selected, _ignored = peq.select_filters(filters, strategy, 5)
        actual = "+".join(str(f.number) for f in selected)
        if actual != selected_ids:
            fail(f"strategy {strategy} selected {actual}, expected {selected_ids}")
        errors[strategy] = strategy_error(filters, selected)[0]
    if not errors["best"] < errors["largest"] < errors["first"]:
        fail(f"unexpected strategy error ordering: {errors}")
    note("filter-selection strategies match expected sample behavior")


def check_plotter(tmp: Path) -> None:
    out = tmp / "plots"
    sample = ROOT / "samples" / "filter-strategy" / "best.bin"
    run([str(TOOLS / "plot_cxd3778gf_tct_response.py"), "--out-dir", str(out), "--chunk-file", f"best={sample}"])
    for name in (
        "cxd3778gf_tct_response_half0_176400hz.svg",
        "cxd3778gf_tct_response_half1_192000hz.svg",
        "cxd3778gf_tct_response_summary.txt",
    ):
        if not (out / name).is_file() or (out / name).stat().st_size == 0:
            fail(f"plotter did not create {name}")
    note("plotter accepts direct custom chunk files")


def check_default_tone_clock() -> None:
    if peq.DEFAULT_TONE_FS_441 != 176400.0 or peq.DEFAULT_TONE_FS_48 != 192000.0:
        fail(
            "default tone-DSP clocks changed unexpectedly: "
            f"{peq.DEFAULT_TONE_FS_441:g}/{peq.DEFAULT_TONE_FS_48:g}"
        )
    probe = peq.Filter("PK", 1000.0, 12.0, 1.0)
    at_center = peq.response_db_for_filters([probe], [1000.0], peq.DEFAULT_TONE_FS_48)[0]
    if abs(at_center - 12.0) > 1e-6:
        fail(f"192 kHz RBJ center response is {at_center:.6f} dB, expected 12 dB")
    note("default 176.4/192 kHz tone-DSP clocks preserve the requested center frequency")


def check_full_table_builder(tmp: Path) -> None:
    out = tmp / "tc_1291.sample-sg.tbl"
    sample = ROOT / "samples" / "sample-autoeq.txt"
    base = tmp / "identity.tbl"
    tct.make_identity_table(base)
    run([
        str(TOOLS / "autoeq_to_cxd3778gf_table.py"),
        str(sample),
        str(out),
        "--base-table",
        str(base),
        "--target",
        "sg",
    ])
    if out.stat().st_size != tct.BODY_SIZE + tct.CHECKSUM_SIZE:
        fail(f"full table size is {out.stat().st_size}, expected {tct.BODY_SIZE + tct.CHECKSUM_SIZE}")
    base_body, _ = tct.read_table(base)
    new_body, expected = tct.read_table(out)
    if expected != tct.checksum(new_body):
        fail("full table checksum is invalid")
    changed = []
    for index, name in enumerate(tct.TABLE_NAMES):
        lo = index * tct.CHUNK_SIZE
        hi = lo + tct.CHUNK_SIZE
        if base_body[lo:hi] != new_body[lo:hi]:
            changed.append(name)
    if changed != ["sg"]:
        fail(f"full table builder changed chunks {changed}, expected ['sg']")
    sample_blob = tmp / "sample.proc"
    run([str(TOOLS / "autoeq_to_cxd3778gf_peq.py"), str(sample), str(sample_blob)])
    sg_index = tct.TABLE_NAMES.index("sg")
    sg_lo = sg_index * tct.CHUNK_SIZE
    sg_hi = sg_lo + tct.CHUNK_SIZE
    if new_body[sg_lo:sg_hi] != sample_blob.read_bytes()[:tct.CHUNK_SIZE]:
        fail("full table sg chunk does not match generated PEQ body")
    note("full tc_*.tbl builder replaces exactly the target chunk with valid checksum")


def check_measurement_wav(tmp: Path) -> None:
    wav = tmp / "peq-measurement.wav"
    manifest = tmp / "peq-measurement.csv"
    run([str(TOOLS / "make_peq_measurement_wav.py"), str(wav), "--manifest", str(manifest)])
    _sr, result = measurement.analyze(wav, manifest)
    levels = [measurement.db(value) for value in result.values()]
    worst = max(abs(level + 18.0) for level in levels)
    if worst > 0.08:
        fail(f"measurement WAV self-analysis deviates from -18 dBFS by {worst:.3f} dB")
    note("measurement WAV self-analysis is near -18 dBFS")


def check_syntax() -> None:
    run([sys.executable, "-m", "py_compile", *(str(p) for p in sorted(TOOLS.glob("*.py")))])
    run(["bash", "-n", str(TOOLS / "apply_cxd3778gf_peq_adb.sh")])
    note("Python and bash syntax checks pass")


def cleanup_pycache() -> None:
    for path in TOOLS.rglob("__pycache__"):
        shutil.rmtree(path)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cxd3778gf-peq-verify-") as td:
        tmp = Path(td)
        check_syntax()
        check_default_tone_clock()
        check_empty_matches_sg(tmp)
        check_sample_quantization(tmp)
        check_q37_preamp_distribution(tmp)
        check_filter_strategies()
        check_plotter(tmp)
        check_full_table_builder(tmp)
        check_measurement_wav(tmp)
    cleanup_pycache()
    note("toolchain verification complete")


if __name__ == "__main__":
    main()
