# CXD3778GF custom PEQ path research

中文方法与复现实验规范见：

```text
docs/cxd3778gf-methods.zh.md
```

Workspace: `/home/neoncloud/walkman-tuning-guide` in WSL. The Windows repo is treated as archive/source material only.

## What Wampy confirms

- Wampy targets NW-A50/ZX300/WM1 series and exposes hidden SoundServiceFw filters including 6-band EQ, 10-band EQ, tone control, VPT, DC phase, vinylizer and direct source.
- Its equalizer-filter writeup shows those filters live in `libSoundServiceFw.so`; Wampy uses LD_PRELOAD/shared memory to force filter-chain availability and set parameters.
- Its volume-table writeup points to the kernel codec card `cxd3778gf` and the boot-time `dacdat` writes into `/proc/icx_audio_cxd3778gf_data/{ovt,ovt_dsd,tct}`.

## Kernel-side finding

The CXD3778GF driver already has the most useful hardware injection point:

- `CODEC_RAM_WORD_SIZE = 5`
- `CODEC_RAM_SIZE = 5 * 32 * 2 = 320`
- `cxd3778gf_tone_control_table[9][320]`
- `/proc/icx_audio_cxd3778gf_data/tct` accepts `9 * 320 + 8 = 2888` bytes.
- `/proc/icx_audio_cxd3778gf_data/tct_*` exposes one 320-byte table per output/headphone case.
- `adjust_tone_control()` selects one of the 9 tables, then writes it to `CXD3778GF_MEM_ADDR` / `CXD3778GF_MEM_WDAT` in 40-byte bursts.

This makes PEQ the better target than convolution. The ALSA/codec path does not expose PCM samples in this driver, so software convolution in this layer would require a much larger ASoC platform/PCM hook. PEQ can plausibly fit the existing hardware tone RAM path.

## A50 live-device validation

Device connected by ADB through `E:\Downloads\platform-tools\adb.exe`:

- Serial: `10459245524948`
- Product: `BBDMP5_linux`
- Android release: `5.0`
- Shell UID: `root`
- `/proc/icx_audio_cxd3778gf_data` exposes `ovt`, `ovt_dsd`, `tct`, and all `tct_*` nodes.
- `/system/usr/share/audio_dac/tc_1291.tbl` is 2888 bytes.
- `/proc/icx_audio_cxd3778gf_data/tct` is 2880 bytes.
- `tc_1291.tbl[:-8] == proc_tct.bin` is true.
- Each 320-byte `tct_*` node matches its chunk in `tc_1291.tbl`.
- Reapplying the original `tc_1291.tbl` to `/proc/.../tct` succeeds and readback MD5 stays unchanged.

Dump location:

- WSL: `/home/neoncloud/walkman-tuning-guide/device-dumps/a50-10459245524948`
- Windows archive copy: `E:\Downloads\zx300-a50-probe`

## Kernel prototype

Modified WSL source tree: `/home/neoncloud/walkman-tuning-guide/kernel/soc/codecs/cxd3778gf`.

Prototype behavior:

- Adds `cxd3778gf_custom_tone_control_table[320]`.
- Adds `cxd3778gf_custom_tone_control_enable`.
- Adds `/proc/icx_audio_cxd3778gf_data/peq` accepting one 320-byte custom tone RAM blob plus the usual 8-byte checksum.
- Adds `/proc/icx_audio_cxd3778gf_data/peq_enable` accepting text `0` or `1`.
- When enabled, `adjust_tone_control()` ignores Sony's selected headphone table and writes the custom `peq` RAM instead.
- Keeps normal `tct`/`tct_*` writes mapped to `TABLE_ID_TONE_CONTROL`; the custom `peq` table maps to `TABLE_ID_CUSTOM_TONE_CONTROL`. This avoids array-index/table-id drift after inserting the new proc port.

This is intentionally raw-table based. It avoids baking an unverified coefficient format into the kernel. The current patch dry-runs cleanly against a temporary tree reconstructed from the saved `.orig` files. It has not been compiled yet because the WSL environment does not currently contain the matching ARM/Android kernel toolchain.

## Helper tool

`/home/neoncloud/walkman-tuning-guide/tools/cxd3778gf_tct_tool.py`

Supported operations:

- `inspect <table>`: validate checksum and print per-320-byte chunk hashes.
- `split <table> <out_dir>`: split a 2880/2888-byte table into 9 raw chunks.
- `replace-chunk <base_table> <name> <chunk> <out>`: replace one chunk and emit a checksummed 2888-byte table.
- `add-checksum <body> <out>`: append Sony checksum to a 320-byte chunk or 2880-byte body.


## PEQ coefficient model

The stock `tc_1291.tbl` strongly suggests this layout for each 320-byte table:

- Two 160-byte halves. Current working assumption: 44.1 kHz family and 48 kHz family.
- Each half has 32 words.
- Each word is a signed 40-bit big-endian fixed-point value.
- Q37 scaling fits the identity table exactly: `20 00 00 00 00` decodes to `1.0`.
- The first 25 words are five biquad sections: `b0, b1, b2, -a1, -a2`.
- The remaining 7 words are zero padding/reserved.

Evidence: the stock general headphone table decodes to five identity sections in both halves. NW500/NW750/NC31 tables decode to stable IIR-looking coefficients in the same section positions.

Frequency-response sanity check:

- Plot tool: `/home/neoncloud/walkman-tuning-guide/tools/plot_cxd3778gf_tct_response.py`
- Stock plots:
  - `/home/neoncloud/walkman-tuning-guide/plots/cxd3778gf_tct_response_half0_44100hz.svg`
  - `/home/neoncloud/walkman-tuning-guide/plots/cxd3778gf_tct_response_half1_48000hz.svg`
- `sg` plots as exactly `0.00 dB` across the band.
- NW500/NW750 plots show plausible headphone compensation: strong low-frequency attenuation, a small lift around 500 Hz, and cuts around 1-2 kHz.
- NC31/SNC31 plots are more moderate broad corrections.

This is strong evidence for the IIR interpretation: random bit-field or endian mistakes would not normally produce stable, smooth, earphone-specific EQ curves while also making the identity table exactly flat.

## PEQ generator and stock-kernel apply path

New tool:

`/home/neoncloud/walkman-tuning-guide/tools/autoeq_to_cxd3778gf_peq.py`

It parses AutoEq-style lines such as:

```text
Preamp: -3.0 dB
Filter 1: ON PK Fc 1000 Hz Gain 3.0 dB Q 1.00
Filter 2: ON PK Fc 4000 Hz Gain -2.0 dB Q 1.20
```

Supported filter types: `PK`, `LS`, `HS`. The cxd3778gf tone RAM has room for at most five biquads. By default the tool keeps the first five enabled filters to preserve input order and old behavior. For AutoEq profiles with more than five filters, the generator also supports explicit selection strategies:

- `--filter-strategy first`: keep the first N filters, default and backwards-compatible.
- `--filter-strategy largest`: keep the N filters with the largest absolute gain, then write them in original order.
- `--filter-strategy wide`: prefer broad/high-impact filters; shelves get a bonus and peaking filters are weighted by `gain / sqrt(Q)`.
- `--filter-strategy greedy`: iteratively add the filter that most reduces RMS dB error against the full input response.
- `--filter-strategy best`: enumerate N-filter combinations and choose the subset with the lowest RMS dB error against the full input response; falls back to greedy if the combination count is too large.
- `--max-sections 1..5`: optionally use fewer than five sections.

It emits a 328-byte blob: 320-byte RAM body plus the 8-byte Sony checksum.

Full table builder:

`/home/neoncloud/walkman-tuning-guide/tools/autoeq_to_cxd3778gf_table.py`

This wraps the PEQ generator and emits a complete 2888-byte `tc_*.tbl` style table by replacing one of the nine 320-byte chunks in a base table and recomputing the full-table checksum. Example:

```sh
tools/autoeq_to_cxd3778gf_table.py samples/sample-autoeq.txt samples/full-table/tc_1291.sample-sg.tbl \
  --base-table device-dumps/a50-10459245524948/tc_1291.tbl \
  --target sg --filter-strategy best
```

Validation example output: `/home/neoncloud/walkman-tuning-guide/samples/full-table/tc_1291.sample-sg.tbl`. It is useful for archive/boot-time table experiments. The helper does not write `/system` or modify firmware files by itself.

New ADB helper:

`/home/neoncloud/walkman-tuning-guide/tools/apply_cxd3778gf_peq_adb.sh`

Usage:

```sh
tools/apply_cxd3778gf_peq_adb.sh --input autoeq.txt --target sg
tools/apply_cxd3778gf_peq_adb.sh --input autoeq.txt --target sg --filter-strategy best
tools/apply_cxd3778gf_peq_adb.sh --restore --target sg
```

The helper writes to stock kernel nodes such as `/proc/icx_audio_cxd3778gf_data/tct_sg`, so a rebuilt kernel is not strictly required for experiments. It backs up the target before applying. `--restore` uses the saved local backup and does not overwrite it from the device. The helper now also pulls the proc node back after apply/restore and verifies the 320-byte readback against the expected body.

Validation performed:

- Empty AutoEq input generates a body identical to stock `tct_sg`.
- A sample PEQ produces the expected software frequency response shape.
- Applying the sample PEQ to non-default target `tct_nnw500` changes readback exactly to the generated 320-byte body.
- Restoring `tct_nnw500` returns readback exactly to the original stock MD5 `c0c058b47d8202973bdcff8654791eb9`.
- Applying the sample PEQ to active/general target `tct_sg` changes proc readback exactly to the generated body MD5 `cfab10ea2249e6f34b3ee20187515b7f`.
- Restoring `tct_sg` returns proc readback to the pre-test/original stock MD5 `ed7c873429c32ac16b824afb698a8cb1`.

Additional custom-PEQ plotting validation:

- `plot_cxd3778gf_tct_response.py` now accepts direct custom chunks with `--chunk-file name=/path/to/blob`; the blob may be either 320-byte raw tone RAM or 328-byte tone RAM plus checksum.
- Sample AutoEq input: `/home/neoncloud/walkman-tuning-guide/samples/sample-autoeq.txt`
- Generated sample blob: `/home/neoncloud/walkman-tuning-guide/samples/sample-autoeq.cxd3778gf-peq.bin`
- Sample plots:
  - `/home/neoncloud/walkman-tuning-guide/plots/sample-peq/cxd3778gf_tct_response_half0_44100hz.svg`
  - `/home/neoncloud/walkman-tuning-guide/plots/sample-peq/cxd3778gf_tct_response_half1_48000hz.svg`
- The sample response matches the designed RBJ filters after Q37 encoding with max coefficient error about `3.5e-12` and max response error below `1e-7 dB`.

The sample uses `Preamp -4 dB`, `LS +3 dB @ 105 Hz`, `PK -2.5 dB @ 950 Hz`, `PK +4 dB @ 3100 Hz`, and `HS -1.5 dB @ 9000 Hz`; the plotted curve follows that expectation.

Filter-selection validation for profiles with more than five filters:

- Input: `/home/neoncloud/walkman-tuning-guide/samples/filter-strategy/autoeq-8filters.txt`
- Outputs: `/home/neoncloud/walkman-tuning-guide/samples/filter-strategy/{first,largest,wide,greedy,best}.bin`
- Plots: `/home/neoncloud/walkman-tuning-guide/plots/filter-strategy/cxd3778gf_tct_response_half0_44100hz.svg` and `half1_48000hz.svg`
- Error table: `/home/neoncloud/walkman-tuning-guide/plots/filter-strategy/error-summary.csv`
- In the 8-filter sample, RMS error against the full response is `first=2.1714 dB`, `largest=0.8867 dB`, `wide=0.8867 dB`, `greedy=0.9782 dB`, `best=0.7684 dB`.
- Empty-input compatibility was rechecked after this change: `--body-only` output still matches stock `tct_sg`.

## Analog measurement helper

Two small pure-Python tools are available for the remaining hardware-output check:

- `/home/neoncloud/walkman-tuning-guide/tools/make_peq_measurement_wav.py` creates a stepped-sine WAV plus a CSV manifest.
- `/home/neoncloud/walkman-tuning-guide/tools/analyze_peq_measurement.py` measures each stepped-sine segment in a captured WAV and can compare PEQ-vs-flat delta in dB.

Generated stimulus:

- `/home/neoncloud/walkman-tuning-guide/samples/peq-measurement-44100.wav`
- `/home/neoncloud/walkman-tuning-guide/samples/peq-measurement-44100.csv`

Recommended measurement flow:

1. Play `peq-measurement-44100.wav` on the Walkman with stock/restored `tct_sg` and record the analog headphone/line output as `flat.wav`.
2. Apply the sample or target PEQ to `tct_sg`, play the same WAV again at the same volume, and record as `peq.wav`.
3. Restore `tct_sg`.
4. Analyze with:

```sh
tools/analyze_peq_measurement.py --manifest samples/peq-measurement-44100.csv --flat flat.wav --peq peq.wav --csv-out measurement-delta.csv
```

The generated stimulus self-checks at roughly `-18 dBFS` on every tone when analyzed directly.

## Regression self-test

Run this from the WSL workspace after editing any helper script:

```sh
tools/verify_peq_toolchain.py
```

It checks:

- Python and bash syntax.
- Empty AutoEq input still generates a body identical to stock `tct_sg`.
- Sample PEQ Q37 quantization stays below tolerance.
- `first`, `largest`, `wide`, `greedy`, and `best` filter-selection strategies match the 8-filter sample expectations.
- The plotter can read a direct custom chunk/blob.
- The full `tc_*.tbl` builder replaces exactly the requested chunk and emits a valid checksum.
- The stepped-sine measurement WAV self-analyzes near `-18 dBFS`.

Latest run: all checks passed.

## Next technical blocker

The raw coefficient encoding now has a working Q37/biquad model, an experimental generator, and a verified stock-kernel proc write/readback path for both non-default and `sg` tone-control targets. The remaining unknown is analog/audio-output confirmation that the cxd3778gf interprets the generated coefficients with the exact RBJ sign convention and sample-rate-half assumption. Next steps:

1. Play a known test signal while applying/restoring a mild `sg` PEQ and capture the analog output.
2. Measure the captured output with a loopback/audio analyzer to confirm RBJ sign convention and the 44.1/48 half mapping.
3. Decide whether the clean kernel `/proc/.../peq` prototype is worth building, or whether stock `tct_*` injection is sufficient.
4. Improve AutoEq reduction beyond subset selection, e.g. fit/merge excess filters by optimizing five available section parameters.
