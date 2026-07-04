# 备份与救砖准备 / Backup and Recovery Preparation

> [!WARNING]
> **请在 ADB 解锁、写入 tone table、安装内核模块或修改开机脚本之前完成备份。**
>
> 按本项目提示一步一步做，正常情况下不会有刷砖风险；但任何固件修改、root/ADB 操作、`/proc` 写入和内核模块加载都可能因为断电、误选文件、设备差异或脚本使用错误而进入异常状态。提前备份是最便宜的保险。
>
> **Back up before ADB unlock, tone-table writes, kernel-module installation, or boot-script changes.** Following the guide carefully should not brick the player, but mistakes and device differences can still happen.

## 推荐工具 / Recommended Tool

Windows 用户优先使用 `unknown321` 的 Walkman Backup/Restore Tool:

- [unknown321/wbrt](https://github.com/unknown321/wbrt)

该工具用于 MT8590-based Walkman 的备份和还原，项目 README 列出的设备包括：

- NW-A30 / A40 / A50
- ZX300
- WM1A / WM1Z
- DMP-Z1

The tool is intended to create and restore backups for MT8590-based Walkman players. Its README also notes that bootloop recovery is possible only if you made a backup beforehand.

## 参考教程 / Reference Guide

Wampy 的备份文档也建议在安装极小概率出问题时保留备份，并给出 Windows、Linux、mtkclient 等路径：

- [unknown321/wampy BACKUP.md](https://github.com/unknown321/wampy/blob/master/BACKUP.md)

Wampy's backup document recommends having a backup before installation goes wrong, even if that is unlikely, and documents Windows/Linux/mtkclient approaches.

## 建议备份内容 / What to Back Up

最低建议：

- 系统分区或整机镜像。
- 当前官方固件安装包。
- `/system/usr/share/audio_dac/tc_*.tbl` 原厂调音表。
- `/proc/icx_audio_cxd3778gf_data/tct` 读出的当前 tone table body。
- 自己设备的序列号、型号、固件版本记录。

Recommended minimum:

- system partitions or a full-device image;
- the original official firmware package;
- stock `/system/usr/share/audio_dac/tc_*.tbl` tone tables;
- current `/proc/icx_audio_cxd3778gf_data/tct` readback;
- device serial, model, and firmware-version notes.

## 重要注意 / Important Notes

- 不要使用其他设备的备份恢复到你的播放器，即使型号相同也不建议。工厂参数、序列号和分区内容可能不同。
- 不要把自己的完整备份、设备 dump、序列号或原厂固件上传到本项目 issue 或公开仓库。
- 还原前再次确认目标文件来自自己的设备。
- 如果你没有备份，不要把“救砖”当成必然可行。

- Do not restore another device's backup to your player, even if the model matches.
- Do not upload full backups, device dumps, serial numbers, or Sony firmware to public issues or repositories.
- Before restoring, verify that the image came from your own device.
- Without a prior backup, recovery is not guaranteed.
