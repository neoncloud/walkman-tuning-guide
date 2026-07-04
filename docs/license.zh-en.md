# 版权与许可 / Copyright and License

本项目不采用 GPL、MIT、Apache 等允许商业使用的许可证，因为作者明确保留“禁止商用”的权利。标准 GPL 允许商业使用，因此不符合本项目目标。

This project does not use GPL, MIT, Apache, or other licenses that allow commercial use, because the author explicitly reserves non-commercial rights. Standard GPL allows commercial use, so it does not match the goal of this repository.

## 许可选择 / License Choice

本仓库采用现有的大众非商业许可：**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)**。

This repository uses an existing mainstream non-commercial license: **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)**.

它不是 OSI 意义上的开源软件许可证；它是广泛使用的 Creative Commons 非商业许可。选择它的核心原因是明确禁止付费安装、付费刷机、付费调音、付费调音包和商业改机服务，同时允许非商业学习、分享和改作，但改作必须继续使用同一许可分享。

It is not an OSI open-source software license; it is a widely used Creative Commons non-commercial license. The core reason for using it is to clearly prohibit paid installation, paid flashing, paid tuning, paid tuning packs, and commercial modification services, while still allowing non-commercial study, sharing, and adaptations under the same license.

它的核心含义是：

The core meaning is:

- 可以个人学习、研究、验证、备份、非商业分享和非商业改作。  
  Personal study, research, validation, backup, non-commercial sharing, and non-commercial adaptations are allowed.
- 禁止商业使用。  
  Commercial use is prohibited.
- 分享或发布改作时，必须署名、注明修改，并继续使用 CC BY-NC-SA 4.0。  
  Shared adaptations must include attribution, indicate changes, and remain under CC BY-NC-SA 4.0.

## 什么是商业使用 / What Counts as Commercial Use

以下都属于禁止范围：

The following are prohibited:

- 付费安装、付费刷机、付费调音服务。  
  Paid installation, flashing, or tuning services.
- 销售调音表、固件包、改机设备。  
  Selling tuning tables, firmware packages, or modified devices.
- 把本项目集成到商业固件、商业播放器、商业维修/改机服务。  
  Integrating this work into commercial firmware, commercial players, or commercial repair/modification services.
- 作为闭源商业产品的一部分。  
  Using it as part of a closed-source commercial product.
- 营利组织内部使用本项目来提供产品或服务。  
  Internal use by a for-profit organization to provide products or services.

## 第三方内容 / Third-Party Materials

本项目不包含也不授权以下内容：

This project does not include or license:

- Sony 固件、Sony 二进制文件、原厂调音表。  
  Sony firmware, Sony binaries, or stock tuning tables.
- 设备 dump。  
  Device dumps.
- AutoEq 数据集或第三方耳机测量数据。  
  AutoEq datasets or third-party headphone measurements.
- 第三方项目源码。  
  Source code from third-party projects.

用户必须从合法来源自行取得这些材料，并遵守对应项目或权利人的许可。

Users must obtain those materials legally from their original sources and follow their licenses.

## 内核模块标记 / Kernel Module License Marker

Linux kernel modules may contain a `MODULE_LICENSE("GPL")` string. In this repository it is used as a kernel loader compatibility marker for the target Sony/Linux kernel environment.

Linux 内核模块源码中可能包含 `MODULE_LICENSE("GPL")` 字符串。在本仓库中，它用于目标 Sony/Linux kernel 环境下的模块加载兼容性标记。

This marker does not grant commercial permission for this repository. The repository-level permission remains CC BY-NC-SA 4.0 in [LICENSE](../LICENSE).

这个标记不代表本仓库允许商业使用。本仓库整体授权仍以 [LICENSE](../LICENSE) 中的 CC BY-NC-SA 4.0 为准。

## 免责声明 / Disclaimer

本项目会修改播放器音频路径，可能需要 root、ADB、固件修改和内核模块。错误操作可能导致设备无法启动、音频异常、数据丢失或听力风险。

This project changes the player's audio path and may require root, ADB, firmware modification, and kernel modules. Mistakes may cause boot failure, audio malfunction, data loss, or hearing risk.

所有内容按原样提供，作者不提供适配保证，也不承担任何后果。

Everything is provided as-is, without compatibility guarantees or liability.
