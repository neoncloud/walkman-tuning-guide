# ADB 解锁指南 / ADB Unlock Guide

> 先备份原始固件包、播放器数据和当前设置。不要直接修改唯一一份官方固件。  
> Back up the original firmware package, player data, and current settings first. Never modify your only copy of the official firmware.

## 为什么需要 ADB / Why ADB Is Needed

本项目需要通过 ADB 完成备份、写入 tone table、加载/卸载内核模块、读取 dmesg 和验证 proc 节点。没有 ADB，就无法可靠部署和恢复。

This project uses ADB to back up tables, write tone tables, load/unload kernel modules, read dmesg, and verify proc nodes. Without ADB, deployment and recovery are not reliable.

## 基本思路 / Basic Idea

Walkman 固件安装器会在升级过程中执行 shell 脚本。实用的解锁方式是复制一份官方固件包，解包后修改安装脚本，在安装时注入开启 ADB 的命令，然后重新打包并让官方安装器使用这份修改后的固件。

Walkman firmware installers execute shell scripts during update. A practical unlock path is to copy the official firmware package, unpack it, patch the installer script to enable ADB during installation, repack it, and let the official installer use the patched package.

重要限制：Sony 官方固件安装器面向 Windows。Linux/WSL 下的固件解包/回包通常依赖 Rockbox 或社区逆向得到的非官方二进制工具，因此普通用户建议优先使用 Windows / PowerShell 流程；bash 脚本主要服务 WSL 自动化和已有 Linux 工具链的用户。

Important limitation: Sony's official firmware updater is Windows-oriented. Linux/WSL unpack/repack workflows usually depend on Rockbox or other community reverse-engineered unofficial binary tools. Normal users should prefer the Windows / PowerShell flow; the bash script is mainly for WSL automation and users who already have a Linux firmware toolchain.

典型注入命令：

Typical injected commands:

```sh
setprop persist.service.adb.enable 1
setprop persist.sys.usb.config adb
start adbd
```

不同机型、不同固件版本的安装脚本路径可能不同，所以脚本必须保守处理：先 dry-run，确认候选脚本，再显式 `--apply`。

Installer script paths differ across models and firmware versions, so the patcher must be conservative: dry-run first, confirm candidate scripts, then use explicit `--apply`.

## 一键脚本 / Helper Script

本仓库提供 Windows 和 bash 两套入口：

This repository provides both Windows and bash entry points:

```powershell
scripts\patch_firmware_adb_unlock.ps1
scripts\patch_firmware_adb_unlock.cmd
```

```bash
scripts/patch_firmware_adb_unlock.sh
```

推荐 Windows 流程：

Recommended Windows flow:

```powershell
cd C:\path\to\walkman-tuning-guide

# 1. 先 dry-run，只检查不写入
scripts\patch_firmware_adb_unlock.ps1 `
  -Firmware C:\path\to\NW_WM_FW.UPG `
  -UpgTool C:\path\to\upgtool-v3.exe

# 2. 确认输出日志后再应用
scripts\patch_firmware_adb_unlock.ps1 `
  -Firmware C:\path\to\NW_WM_FW.UPG `
  -UpgTool C:\path\to\upgtool-v3.exe `
  -Apply
```

也可以从 `cmd.exe` 调用：

You can also call it from `cmd.exe`:

```cmd
scripts\patch_firmware_adb_unlock.cmd -Firmware C:\path\to\NW_WM_FW.UPG -UpgTool C:\path\to\upgtool-v3.exe -Apply
```

WSL / bash 流程：

WSL / bash flow:

```bash
cd /home/neoncloud/walkman-tuning-guide

# 1. 先 dry-run，只检查不写入
bash scripts/patch_firmware_adb_unlock.sh \
  --firmware /path/to/original/NW_WM_FW.UPG \
  --upgtool /path/to/upgtool-v3.exe

# 2. 确认输出日志后再应用；Linux 回包依赖 Rockbox/社区 upgtool 等非官方工具
bash scripts/patch_firmware_adb_unlock.sh \
  --firmware /path/to/original/NW_WM_FW.UPG \
  --upgtool /path/to/upgtool-v3.exe \
  --apply
```

脚本目标：

Script goals:

- 不原地修改官方固件。  
  Never modify the official package in place.
- 创建工作副本。  
  Create a working copy.
- 自动寻找候选安装脚本。  
  Search candidate installer scripts.
- 只插入一次带标记的 ADB 解锁块。  
  Insert a marked ADB unlock block only once.
- 重新打包后提示用户替换安装器使用的固件文件。  
  Repack and guide the user to replace the firmware file used by the installer.

## 安装后的验证 / Verification

固件安装完成并重启后，在 WSL 中使用 E 盘 platform-tools：

After firmware installation and reboot, use the E-drive platform-tools from WSL:

```bash
export ADB=/mnt/e/Downloads/platform-tools/adb.exe
"$ADB" devices
"$ADB" shell id
"$ADB" shell 'ls /proc/icx_audio_cxd3778gf_data'
```

理想情况下，`id` 能看到 root 或足够权限，且 `/proc/icx_audio_cxd3778gf_data/tct` 存在。

Ideally, `id` shows root or sufficient privileges, and `/proc/icx_audio_cxd3778gf_data/tct` exists.

## 失败处理 / Recovery Notes

- 如果设备没有出现在 `adb devices`，先检查 USB 模式、线缆、Windows 设备管理器和播放器 USB 设置。  
  If the device does not appear in `adb devices`, check USB mode, cable, Windows Device Manager, and player USB settings.
- 如果安装器拒绝固件，使用未修改的原始固件恢复。  
  If the installer rejects the package, restore with the untouched original firmware.
- 如果播放器异常，优先撤回自定义模块和 autoload，再恢复 stock table。  
  If the player behaves abnormally, remove custom modules and autoload first, then restore the stock table.
