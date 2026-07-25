param(
    [string]$OutputDir = "experiments\measurements\zx300a-usb-dac-all-sample-rates",
    [string]$Adb = "E:\Downloads\platform-tools\adb.exe",
    [string]$Python = "C:\Python312\python.exe",
    [double]$LevelDbfs = -36.0,
    [int]$Periods = 8,
    [int[]]$Rates = @(44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000),
    [switch]$SkipChannelMap
)

# WALKMAN 以 8 档 WDM-KS 独占采样率播放，OsmoPocket3 始终以 48 kHz 录音。
# 每档依次测 identity、两个 half 相同的时钟探针、两个 half 不同的辨认探针。
# 最后单独播放左右声道，确认模拟录音线实际接到哪一侧。
# 所有流关闭后才写 table；无论中途是否失败，最终都会重新应用持久化表。

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
$OutputDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputDir))
$ProbeDir = Join-Path $OutputDir "probes"
$AnalysisDir = Join-Path $OutputDir "analysis"

$RemoteDir = "/data/local/cxd3778gf_tone"
$RemoteIdentity = "$RemoteDir/sample_rate_identity.tbl"
$RemoteCommon = "$RemoteDir/sample_rate_common_probe.tbl"
$RemoteBanks = "$RemoteDir/sample_rate_bank_probe.tbl"
$RemoteRestore = "$RemoteDir/auto_tct.tbl"
$ToneProc = "/proc/icx_audio_cxd3778gf_data/tct"
$ApplyProc = "/proc/cxd3778gf_tone_apply"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（exit=$LASTEXITCODE）：$Program $($Arguments -join ' ')"
    }
}

function Invoke-Adb {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    Invoke-Checked $Adb @Arguments
}

function Apply-RemoteTable {
    param([Parameter(Mandatory = $true)][string]$RemoteTable)
    Invoke-Adb shell "cat '$RemoteTable' > '$ToneProc'"
    Invoke-Adb shell "echo table 5 > '$ApplyProc'"
    Start-Sleep -Milliseconds 400
}

function Measure-Rate {
    param(
        [Parameter(Mandatory = $true)][int]$Rate,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $RateDir = Join-Path $OutputDir "$Rate"
    New-Item -ItemType Directory -Force -Path $RateDir | Out-Null
    Invoke-Checked $Python "tools\measure_audio_loopback.py" `
        "--output-dir" $RateDir `
        "--label" $Label `
        "--signal" "periodic-noise" `
        "--sample-rate" "48000" `
        "--input-sample-rate" "48000" `
        "--output-sample-rate" "$Rate" `
        "--output-channel" "both" `
        "--start-hz" "20" `
        "--end-hz" "20000" `
        "--period-samples" "$Rate" `
        "--periods" "$Periods" `
        "--settle-periods" "2" `
        "--pre-silence" "2" `
        "--post-silence" "2" `
        "--level-dbfs" "$LevelDbfs"
}

function Measure-ChannelMap {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("left", "right")][string]$Channel,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $ChannelDir = Join-Path $OutputDir "channel-map\$Channel"
    New-Item -ItemType Directory -Force -Path $ChannelDir | Out-Null
    Invoke-Checked $Python "tools\measure_audio_loopback.py" `
        "--output-dir" $ChannelDir `
        "--label" $Label `
        "--signal" "periodic-noise" `
        "--sample-rate" "48000" `
        "--input-sample-rate" "48000" `
        "--output-sample-rate" "48000" `
        "--output-channel" $Channel `
        "--start-hz" "20" `
        "--end-hz" "20000" `
        "--period-samples" "48000" `
        "--periods" "$Periods" `
        "--settle-periods" "2" `
        "--pre-silence" "2" `
        "--post-silence" "2" `
        "--level-dbfs" "$LevelDbfs"
}

if (-not (Test-Path -LiteralPath $Adb -PathType Leaf)) { throw "找不到 adb：$Adb" }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "找不到 Python：$Python" }
if (Get-Process -Name python, pythonw -ErrorAction SilentlyContinue) {
    throw "检测到 Python 进程。请先停止其他播放或录音任务。"
}

New-Item -ItemType Directory -Force -Path $OutputDir, $ProbeDir, $AnalysisDir | Out-Null
Invoke-Checked $Python "-c" "import numpy, scipy, matplotlib, sounddevice"
Invoke-Checked $Python "tools\make_cxd3778gf_sample_rate_probes.py" $ProbeDir

Invoke-Adb start-server
Invoke-Adb wait-for-device
Invoke-Adb shell "test -f '$RemoteRestore' && test -e '$ApplyProc'"
Invoke-Adb push (Join-Path $ProbeDir "identity.tbl") $RemoteIdentity
Invoke-Adb push (Join-Path $ProbeDir "common_1khz_plus12_ref48k.tbl") $RemoteCommon
Invoke-Adb push (Join-Path $ProbeDir "asymmetric_halves.tbl") $RemoteBanks

try {
    foreach ($Rate in $Rates) {
        Write-Host "===== USB DAC $Rate Hz ====="
        Apply-RemoteTable $RemoteIdentity
        Measure-Rate $Rate "identity"

        Apply-RemoteTable $RemoteCommon
        Measure-Rate $Rate "common_probe"

        Apply-RemoteTable $RemoteBanks
        Measure-Rate $Rate "bank_probe"
    }

    if (-not $SkipChannelMap) {
        Write-Host "===== 48 kHz 左右声道映射 ====="
        Apply-RemoteTable $RemoteIdentity
        Measure-ChannelMap "left" "identity"
        Measure-ChannelMap "right" "identity"

        Apply-RemoteTable $RemoteBanks
        Measure-ChannelMap "left" "bank_probe"
        Measure-ChannelMap "right" "bank_probe"
    }
}
finally {
    Apply-RemoteTable $RemoteRestore
}

$RateList = $Rates -join ","
Invoke-Checked $Python "tools\analyze_cxd3778gf_sample_rates.py" `
    $OutputDir `
    "--probe-dir" $ProbeDir `
    "--rates" $RateList `
    "--output-dir" $AnalysisDir

Invoke-Adb shell "md5sum '$RemoteRestore'; cat '$ApplyProc'"
Write-Host "全采样率报告：$AnalysisDir\REPORT.md"
