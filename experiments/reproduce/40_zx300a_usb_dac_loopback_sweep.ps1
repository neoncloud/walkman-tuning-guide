param(
    [string]$OutputDir = "experiments\measurements\zx300a-usb-dac-loopback",
    [string]$Adb = "E:\Downloads\platform-tools\adb.exe",
    [string]$Python = "C:\Python312\python.exe",
    [double]$LevelDbfs = -40.0,
    [double]$SweepSeconds = 12.0,
    [int]$Repetitions = 2
)

# ZX300A USB DAC -> 3.5 mm -> OsmoPocket3 的完整回环扫频实验。
# Windows 负责 WDM-KS 独占播放与录音；ADB 只用于替换、应用和恢复 tone table。

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
$OutputDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputDir))
$RemoteDir = "/data/local/cxd3778gf_tone"
$RemoteTable = "$RemoteDir/usb_dac_sweep.tbl"
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

function Measure-Profile {
    param([Parameter(Mandatory = $true)][string]$Label)
    Invoke-Checked $Python "tools\measure_audio_loopback.py" `
        "--output-dir" $OutputDir `
        "--label" $Label `
        "--sample-rate" "48000" `
        "--start-hz" "20" `
        "--end-hz" "20000" `
        "--sweep-seconds" "$SweepSeconds" `
        "--repetitions" "$Repetitions" `
        "--pre-silence" "2" `
        "--gap-seconds" "1" `
        "--post-silence" "3" `
        "--level-dbfs" "$LevelDbfs"
}

function Apply-Table {
    param([Parameter(Mandatory = $true)][string]$TablePath)
    Invoke-Adb push $TablePath $RemoteTable
    Invoke-Adb shell "cat '$RemoteTable' > '$ToneProc'"
    # USB DAC + 单端耳机输出在本机被驱动判定为 table 5 / tct_sg。
    Invoke-Adb shell "echo table 5 > '$ApplyProc'"
    Invoke-Adb shell "cat '$ApplyProc'"
    Start-Sleep -Milliseconds 500
}

if (-not (Test-Path -LiteralPath $Adb -PathType Leaf)) {
    throw "找不到 adb：$Adb"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "找不到 Python：$Python"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Invoke-Checked $Python "-c" "import numpy, scipy, matplotlib, sounddevice"
Invoke-Adb start-server
Invoke-Adb wait-for-device
Invoke-Adb shell "test -e '$ApplyProc'"
Invoke-Adb shell "mkdir -p '$RemoteDir'; cat '$ToneProc' > '$RemoteDir/usb_dac_sweep_stock.tbl'"

$StockBody = Join-Path $OutputDir "stock_factory_body.tbl"
$StockTable = Join-Path $OutputDir "stock_factory_checksummed.tbl"
Invoke-Adb pull "$RemoteDir/usb_dac_sweep_stock.tbl" $StockBody
Invoke-Checked $Python "tools\cxd3778gf_tct_tool.py" "add-checksum" $StockBody $StockTable
Invoke-Checked $Python "tools\cxd3778gf_tct_tool.py" "inspect" $StockTable

$Profiles = @(
    @{
        Label = "pk_1000_plus12_q1"
        Text = "Preamp: 0.0 dB`nFilter 1: ON PK Fc 1000 Hz Gain 12.0 dB Q 1.00`n"
    },
    @{
        Label = "pk_4000_minus12_q1"
        Text = "Preamp: 0.0 dB`nFilter 1: ON PK Fc 4000 Hz Gain -12.0 dB Q 1.00`n"
    },
    @{
        Label = "three_band_100p9_1000m9_6000p9"
        Text = @"
Preamp: 0.0 dB
Filter 1: ON PK Fc 100 Hz Gain 9.0 dB Q 1.00
Filter 2: ON PK Fc 1000 Hz Gain -9.0 dB Q 1.00
Filter 3: ON PK Fc 6000 Hz Gain 9.0 dB Q 1.00
"@
    }
)

foreach ($Profile in $Profiles) {
    $PeqPath = Join-Path $OutputDir "$($Profile.Label).txt"
    $TablePath = Join-Path $OutputDir "$($Profile.Label).tbl"
    [System.IO.File]::WriteAllText($PeqPath, $Profile.Text, [System.Text.UTF8Encoding]::new($false))
    Invoke-Checked $Python "tools\autoeq_to_cxd3778gf_table.py" `
        $PeqPath $TablePath `
        "--base-table" $StockTable `
        "--target" "sg" `
        "--filter-strategy" "first" `
        "--max-sections" "5"
    $Profile.TablePath = $TablePath
}

$CompletedProfiles = $false
try {
    Write-Host "开始原厂基线；WDM-KS 将独占 WALKMAN 和 OsmoPocket3 音频端点。"
    Measure-Profile "stock_before_1"
    Measure-Profile "stock_before_2"

    foreach ($Profile in $Profiles) {
        Write-Host "应用并测量：$($Profile.Label)"
        Apply-Table $Profile.TablePath
        Measure-Profile $Profile.Label
    }
    $CompletedProfiles = $true
}
finally {
    Write-Host "恢复实验开始前读取的原厂 tone table。"
    Apply-Table $StockTable
}

if (-not $CompletedProfiles) {
    throw "实验中途失败；原厂 tone table 已尝试恢复。"
}

Measure-Profile "stock_after_restore"

$env:MPLCONFIGDIR = Join-Path $OutputDir ".matplotlib"
New-Item -ItemType Directory -Force -Path $env:MPLCONFIGDIR | Out-Null
$AnalyzeArguments = @(
    "tools\analyze_audio_loopback.py",
    "--baseline", "stock_before_1=$(Join-Path $OutputDir 'stock_before_1.wav')",
    "--baseline", "stock_before_2=$(Join-Path $OutputDir 'stock_before_2.wav')",
    "--stock-after", "stock_after_restore=$(Join-Path $OutputDir 'stock_after_restore.wav')",
    "--stock-table", $StockTable,
    "--target", "sg",
    "--half", "1",
    "--sample-rate", "48000",
    "--dsp-sample-rate", "192000",
    "--output-dir", $OutputDir
)
foreach ($Profile in $Profiles) {
    $CapturePath = Join-Path $OutputDir "$($Profile.Label).wav"
    $AnalyzeArguments += @(
        "--profile",
        "$($Profile.Label)=$CapturePath=$($Profile.TablePath)"
    )
}
Invoke-Checked $Python @AnalyzeArguments

Write-Host "扫频实验完成：$(Join-Path $OutputDir 'REPORT.md')"
