param(
    [string]$CustomTable = "out\etymotic-evo-2flange-zx300a\etymotic-evo-2flange-zx300a.tbl",
    [string]$OutputDir = "experiments\measurements\zx300a-usb-dac-etymotic-evo-identity-baseline",
    [string]$Adb = "E:\Downloads\platform-tools\adb.exe",
    [string]$Python = "C:\Python312\python.exe",
    [double]$LevelDbfs = -32.0,
    [int]$Periods = 16
)

# ZX300A USB DAC -> 3.5 mm -> OsmoPocket3 的 EVO 定量回环：
# identity 两次基线 -> EVO -> identity 复测 -> 无条件重新应用 EVO。
# ZX300A 的 stock sg chunk 是五段 identity；现场生成可避免依赖 Sony 原厂文件。

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
$CustomTable = (Resolve-Path -LiteralPath $CustomTable).Path
$OutputDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputDir))

$RemoteDir = "/data/local/cxd3778gf_tone"
$RemoteCustom = "$RemoteDir/auto_tct.tbl"
$RemoteIdentity = "$RemoteDir/loopback_identity.tbl"
$ToneProc = "/proc/icx_audio_cxd3778gf_data/tct"
$ApplyProc = "/proc/cxd3778gf_tone_apply"
$IdentityTable = Join-Path $OutputDir "identity.tbl"

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
    Start-Sleep -Milliseconds 500
}

function Measure-Profile {
    param([Parameter(Mandatory = $true)][string]$Label)
    Invoke-Checked $Python "tools\measure_audio_loopback.py" `
        "--output-dir" $OutputDir `
        "--label" $Label `
        "--signal" "periodic-noise" `
        "--sample-rate" "48000" `
        "--start-hz" "20" `
        "--end-hz" "20000" `
        "--period-samples" "65536" `
        "--periods" "$Periods" `
        "--settle-periods" "2" `
        "--pre-silence" "2" `
        "--post-silence" "3" `
        "--level-dbfs" "$LevelDbfs"
}

if (-not (Test-Path -LiteralPath $Adb -PathType Leaf)) { throw "找不到 adb：$Adb" }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "找不到 Python：$Python" }
if (Get-Process -Name python, pythonw -ErrorAction SilentlyContinue) {
    throw "检测到 Python 进程。请先停止其他播放或录音任务。"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Invoke-Checked $Python "-c" "import numpy, scipy, matplotlib, sounddevice"
Invoke-Adb start-server
Invoke-Adb wait-for-device
Invoke-Adb shell "test -f '$RemoteCustom' && test -e '$ApplyProc'"
Invoke-Checked $Python "tools\cxd3778gf_tct_tool.py" "make-identity" $IdentityTable
Invoke-Adb push $IdentityTable $RemoteIdentity

$LocalCustomMd5 = (Get-FileHash -Algorithm MD5 -LiteralPath $CustomTable).Hash.ToLowerInvariant()
$RemoteCustomMd5 = ((& $Adb shell "md5sum '$RemoteCustom'").Trim() -split "\s+")[0].ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $LocalCustomMd5 -ne $RemoteCustomMd5) {
    throw "设备 auto_tct.tbl 与本地 EVO table 不一致"
}

try {
    Apply-RemoteTable $RemoteIdentity
    Measure-Profile "identity_before_1"
    Measure-Profile "identity_before_2"

    Apply-RemoteTable $RemoteCustom
    Measure-Profile "etymotic_evo_2flange"

    Apply-RemoteTable $RemoteIdentity
    Measure-Profile "identity_after_evo"
}
finally {
    # 无论测量或分析是否报错，设备最终都恢复为用户要求安装的 EVO 表。
    Apply-RemoteTable $RemoteCustom
}

Invoke-Checked $Python "tools\analyze_audio_loopback.py" `
    "--baseline" "identity_before_1=$OutputDir\identity_before_1.wav" `
    "--baseline" "identity_before_2=$OutputDir\identity_before_2.wav" `
    "--profile" "etymotic_evo_2flange=$OutputDir\etymotic_evo_2flange.wav=$CustomTable" `
    "--stock-after" "identity_after_evo=$OutputDir\identity_after_evo.wav" `
    "--stock-table" $IdentityTable `
    "--target" "sg" `
    "--half" "1" `
    "--sample-rate" "48000" `
    "--dsp-sample-rate" "192000" `
    "--output-dir" $OutputDir

Invoke-Adb shell "md5sum '$RemoteCustom'; cat '$ApplyProc'"
Write-Host "EVO 回环报告：$OutputDir\REPORT.md"
