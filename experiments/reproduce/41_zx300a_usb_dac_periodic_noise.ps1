param(
    [string]$OutputDir = "experiments\measurements\zx300a-usb-dac-periodic-noise",
    [string]$Adb = "E:\Downloads\platform-tools\adb.exe",
    [string]$Python = "C:\Python312\python.exe",
    [double]$LevelDbfs = -24.0,
    [int]$Periods = 16,
    [double]$CoefficientFs441 = 44100.0,
    [double]$CoefficientFs48 = 48000.0,
    [string]$ProfilePrefix = ""
)

# OsmoPocket3 会对单音扫频执行自动增益。本实验改用周期宽带信号：
# 所有频率同时存在，AGC 只改变整体电平，不会抹平相对频响。

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
$OutputDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputDir))
$RemoteDir = "/data/local/cxd3778gf_tone"
$RemoteTable = "$RemoteDir/periodic_noise.tbl"
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

function Apply-Table {
    param([Parameter(Mandatory = $true)][string]$TablePath)
    Invoke-Adb push $TablePath $RemoteTable
    Invoke-Adb shell "cat '$RemoteTable' > '$ToneProc'"
    Invoke-Adb shell "echo table 5 > '$ApplyProc'"
    Invoke-Adb shell "cat '$ApplyProc'"
    Start-Sleep -Milliseconds 500
}

if (-not (Test-Path -LiteralPath $Adb -PathType Leaf)) { throw "找不到 adb：$Adb" }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "找不到 Python：$Python" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Invoke-Checked $Python "-c" "import numpy, scipy, matplotlib, sounddevice"
Invoke-Adb start-server
Invoke-Adb wait-for-device
Invoke-Adb shell "test -e '$ApplyProc'"
Invoke-Adb shell "mkdir -p '$RemoteDir'; cat '$ToneProc' > '$RemoteDir/periodic_noise_stock.body'"

$StockBody = Join-Path $OutputDir "stock_factory_body.tbl"
$StockTable = Join-Path $OutputDir "stock_factory_checksummed.tbl"
Invoke-Adb pull "$RemoteDir/periodic_noise_stock.body" $StockBody
Invoke-Checked $Python "tools\cxd3778gf_tct_tool.py" "add-checksum" $StockBody $StockTable
Invoke-Checked $Python "tools\cxd3778gf_tct_tool.py" "inspect" $StockTable

$Profiles = @(
    @{
        Label = "${ProfilePrefix}pk_1000_plus12_q1"
        Text = "Preamp: 0.0 dB`nFilter 1: ON PK Fc 1000 Hz Gain 12.0 dB Q 1.00`n"
    },
    @{
        Label = "${ProfilePrefix}pk_4000_minus12_q1"
        Text = "Preamp: 0.0 dB`nFilter 1: ON PK Fc 4000 Hz Gain -12.0 dB Q 1.00`n"
    },
    @{
        Label = "${ProfilePrefix}three_band_100p9_1000m9_6000p9"
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
        "--fs441" "$CoefficientFs441" `
        "--fs48" "$CoefficientFs48" `
        "--filter-strategy" "first" `
        "--max-sections" "5"
    $Profile.TablePath = $TablePath
}

$CompletedProfiles = $false
try {
    Measure-Profile "stock_before_1"
    Measure-Profile "stock_before_2"
    foreach ($Profile in $Profiles) {
        Apply-Table $Profile.TablePath
        Measure-Profile $Profile.Label
    }
    $CompletedProfiles = $true
}
finally {
    # 只在音频流已关闭的配置切换间隙写表，避免驱动写路径与播放互斥。
    Apply-Table $StockTable
}
if (-not $CompletedProfiles) { throw "实验中途失败；原厂表已尝试恢复。" }

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
Write-Host "周期宽带实验完成：$(Join-Path $OutputDir 'REPORT.md')"
