# ADB 解锁指南 / ADB Unlock Guide

> Always back up the original firmware package and your player data before continuing.

Walkman Linux/Android firmware installers run shell scripts during update. The practical unlock route is to unpack a copy of the official update package, patch the installer script to enable ADB/root debugging, repack the update, and install that modified copy.

典型注入内容如下：

```sh
setprop persist.service.adb.enable 1
setprop persist.sys.usb.config adb
start adbd
```

不同固件的安装脚本位置不同，所以本仓库提供的脚本采用保守策略：

- never modifies the original package in place;
- creates a working copy;
- searches candidate installer scripts;
- inserts a marked block only once;
- requires `--apply` before writing patched output.

Run:

```bash
scripts/patch_firmware_adb_unlock.sh --firmware /path/to/NW_WM_FW.UPG --upgtool /path/to/upgtool-v3.exe
```

Dry-run first, then apply:

```bash
scripts/patch_firmware_adb_unlock.sh --firmware /path/to/NW_WM_FW.UPG --upgtool /path/to/upgtool-v3.exe --apply
```

After repacking, replace the installer package only after comparing hashes and keeping the original firmware package somewhere safe.
