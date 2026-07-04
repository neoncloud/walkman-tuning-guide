# FAQ / 常见问题

## 1. 修改是永久的吗？ / Is the change permanent?

取决于你使用哪一种部署方式。

It depends on the deployment path.

- 只写 `/proc/icx_audio_cxd3778gf_data/tct` 或 `tct_*`：这是运行时写入，重启后通常会回到系统启动时加载的调音表。
- 安装 autoload 或替换系统中的 `tc_*.tbl`：修改会在开机时再次生效，直到你恢复 stock table、移除 autoload 或刷回原固件。
- 推荐实验阶段先使用运行时写入；确认安全和声音符合预期后，再考虑 autoload。

- Writing only `/proc/icx_audio_cxd3778gf_data/tct` or `tct_*` is a runtime change. After reboot, the player usually returns to whichever table is loaded at boot.
- Installing autoload or replacing the system `tc_*.tbl` makes the tuning re-apply at boot until you restore the stock table, remove autoload, or reinstall stock firmware.
- For experiments, use runtime writes first. Consider autoload only after the tuning is safe and confirmed.

## 2. 修改是即时的吗？ / Is the change immediate?

是的。tone table 推送到设备节点并触发对应加载路径后，声音变化会立刻生效。

Yes. After the tone table is pushed to the device node and the corresponding load/apply path is triggered, the sound change is immediate.

- A 系列：写入目标 `tct_*` 或完整 `tct` 节点后，通常可以立刻听到变化。
- ZX300A / ZX / WM：需要先把完整 table 写入 `/proc/icx_audio_cxd3778gf_data/tct`，再通过 `cxd3778gf_tone_apply` 把内存表刷入 tone RAM；执行 `echo apply` 或脚本后立即生效。

- A-series: writing the target `tct_*` or full `tct` node can usually be heard immediately.
- ZX300A / ZX / WM: write the full table to `/proc/icx_audio_cxd3778gf_data/tct`, then use `cxd3778gf_tone_apply` to push it into tone RAM. It takes effect immediately after `echo apply` or the helper script.

## 3. 和其他音效兼容吗？ / Is it compatible with other sound effects?

是的。这个项目修改的是 CXD3778GF tone table 路径，可以和播放器自带的其他音效叠加生效，包括 10-band EQ。

Yes. This project changes the CXD3778GF tone-table path and can stack with the player's built-in sound effects, including the 10-band EQ.

注意叠加会改变总增益和频响。比如自定义 tone table 已经有低频提升，再叠加 10-band EQ 的低频提升，就更容易削波、破音或过响。

Stacking changes total gain and frequency response. For example, if the custom tone table already boosts bass and the 10-band EQ also boosts bass, clipping, distortion, or excessive loudness becomes more likely.

## 4. 和其他自定义固件兼容吗？ / Is it compatible with custom firmware?

据目前理解，著名的 [WalkmanOne for ZX300 series](https://www.mrwalkman.com/p/walkman-one-zx300series.html) 提供多种 sound signature、settings file 和 external tunings。这个项目的工作方式更底层：直接向内核暴露的 CXD3778GF tone table 节点写入完整调音表。

As currently understood, [WalkmanOne for ZX300 series](https://www.mrwalkman.com/p/walkman-one-zx300series.html) provides multiple sound signatures, a settings file, and external tunings. This project works at a lower level: it writes a complete tuning table directly to the CXD3778GF tone-table node exposed by the kernel.

因此，只要自定义固件仍保留同样的内核节点和 `cxd3778gf` 行为，本项目就应该兼容。区别是：本项目写入后，会覆盖当前由 stock firmware 或 custom firmware 选择/加载的调音表；也就是说，自定义固件原来的调音会被本项目的表覆盖，而不是自动混合。

Therefore, as long as the custom firmware keeps the same kernel node and `cxd3778gf` behavior, this project should remain compatible. The important difference is that this project overwrites the currently selected/loaded tone table. The custom firmware's existing tuning is replaced by this project's table, not automatically blended with it.

不兼容的主要情况是：自定义固件修改了内核、移除了这些 proc 节点、改变了 `cxd3778gf` table layout，或者改写了 tone RAM 加载机制。

The main incompatibility cases are: the custom firmware changes the kernel, removes these proc nodes, changes the `cxd3778gf` table layout, or rewrites the tone-RAM load mechanism.

## 5. 加载调音表后声音异常怎么办？ / What if the sound becomes abnormal?

异常包括滋滋声、破音、音量过低、音量过高、某些频段明显塌陷或突然很刺耳。这通常不是播放器坏了，而是滤波器参数不安全或叠加增益过高。

Abnormal sound includes buzzing, crackling, clipping, very low volume, excessive volume, collapsed frequency bands, or harsh peaks. This usually does not mean the player is damaged; it usually means the filter parameters are unsafe or stacked gain is too high.

常见原因：

Common causes:

- 总增益过高：多个 peak/shelf boost 叠加，内部或最终输出削波。
- preamp 不够低：AutoEq profile 有正增益滤波器，但没有足够负 preamp。
- biquad section 太激进：高 Q、大增益、接近 Nyquist 的高频滤波器更容易产生异常。
- 中间级峰值过高：最终频响看起来正常，但 section 内部先大幅放大、后面再抵消，硬件定点路径可能产生噪声。
- 系数量化或符号约定错误：`a1/a2` 符号、Q37 编码、采样率 half 选择错误都会导致完全错误的 IIR。
- 与其他音效叠加过猛：10-band EQ、ClearAudio+、DSEE、Tone Control 等继续叠加会改变余量。

- Total gain is too high: multiple peak/shelf boosts stack and clip internally or at output.
- Preamp is not low enough: the profile has positive-gain filters without enough negative preamp.
- Biquads are too aggressive: high-Q, high-gain, near-Nyquist filters are more likely to misbehave.
- Intermediate section peaks are too high: the final response may look fine, while internal sections boost heavily and later cancel. Fixed-point hardware paths may produce noise.
- Coefficient/sign convention is wrong: `a1/a2` sign, Q37 encoding, or sample-rate-half selection errors can create a completely wrong IIR.
- Other effects stack too hard: 10-band EQ, ClearAudio+, DSEE, Tone Control, and similar effects reduce headroom.

处理建议：

Suggested recovery:

1. 立刻停止播放或降低音量。
2. 恢复 stock table：

   ```bash
   bash scripts/restore_stock_tone_table.sh --device-class a
   # or
   bash scripts/restore_stock_tone_table.sh --device-class zx
   ```

3. 如果启用了 autoload，先卸载 autoload：

   ```bash
   bash experiments/reproduce/99_uninstall_cxd3778gf_tone_apply_autoload.sh
   ```

4. 重新生成更保守的表：降低 boost、增加负 preamp、优先使用 `best`/`wide` 策略、避免极高 Q 和极大增益。
5. 先用小音量试听，再逐步恢复其他音效。

1. Stop playback or lower the volume immediately.
2. Restore the stock table.
3. Remove autoload if it was enabled.
4. Regenerate a more conservative table: lower boosts, add negative preamp, prefer `best`/`wide`, and avoid very high Q or large gains.
5. Test at low volume first, then re-enable other effects gradually.
