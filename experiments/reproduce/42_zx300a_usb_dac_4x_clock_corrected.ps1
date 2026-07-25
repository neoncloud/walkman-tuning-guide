param(
    [string]$OutputDir = "experiments\measurements\zx300a-usb-dac-4x-clock-corrected",
    [string]$Adb = "E:\Downloads\platform-tools\adb.exe",
    [string]$Python = "C:\Python312\python.exe",
    [double]$LevelDbfs = -32.0,
    [int]$Periods = 16
)

# USB DAC 回环证明 tone IIR 在 48 kHz 输入时实际运行于 192 kHz。
# 因而为 44.1/48 kHz 音频族生成系数时，应分别使用 176.4/192 kHz。

$ErrorActionPreference = "Stop"
$Runner = Join-Path $PSScriptRoot "41_zx300a_usb_dac_periodic_noise.ps1"

& $Runner `
    -OutputDir $OutputDir `
    -Adb $Adb `
    -Python $Python `
    -LevelDbfs $LevelDbfs `
    -Periods $Periods `
    -CoefficientFs441 176400 `
    -CoefficientFs48 192000 `
    -ProfilePrefix "corrected_"

if ($LASTEXITCODE -ne 0) {
    throw "4x 时钟校正实验失败（exit=$LASTEXITCODE）。"
}
