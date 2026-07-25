param(
    [string]$DseeOnMetrics = "samples\measurements\zx300a-usb-dac-all-sample-rates\metrics.json",
    [string]$DseeOffMetrics = "samples\measurements\zx300a-usb-dac-all-sample-rates-dsee-off\full\metrics.json",
    [string]$DseeOffRepeatMetrics = "samples\measurements\zx300a-usb-dac-all-sample-rates-dsee-off\outlier-repeat\metrics.json",
    [string]$OutputDir = "experiments\measurements\zx300a-usb-dac-dsee-comparison",
    [string]$Python = "C:\Python312\python.exe"
)

# 只分析已归档数据，不访问音频设备或播放器。

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "找不到输入文件：$Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "找不到 Python：$Python"
}

$DseeOnMetrics = Resolve-InputFile $DseeOnMetrics
$DseeOffMetrics = Resolve-InputFile $DseeOffMetrics
$DseeOffRepeatMetrics = Resolve-InputFile $DseeOffRepeatMetrics
$OutputDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputDir))

& $Python "tools\compare_cxd3778gf_dsee_runs.py" `
    "--dsee-on-metrics" $DseeOnMetrics `
    "--dsee-off-metrics" $DseeOffMetrics `
    "--dsee-off-repeat-metrics" $DseeOffRepeatMetrics `
    "--output-dir" $OutputDir
if ($LASTEXITCODE -ne 0) {
    throw "DSEE 对比分析失败（exit=$LASTEXITCODE）。"
}

Write-Host "DSEE 对比报告：$OutputDir\REPORT.md"
