param(
    [Alias("Input")]
    [string]$ProfilePath = "E:\Downloads\Etymotic Evo (2-flange eartips) ParametricEq.txt",
    [string]$OutputDir = "out\etymotic-evo-2flange-zx300a",
    [string]$Adb = "E:\Downloads\platform-tools\adb.exe",
    [string]$Python = "C:\Python312\python.exe",
    [double]$ToneFs441 = 176400.0,
    [double]$ToneFs48 = 192000.0
)

# Etymotic EVO（2-flange）完整复现实验：
# 1. 从设备当前 proc table 取得 base，并补 Sony 8 字节校验和；
# 2. 用实测的 176.4/192 kHz tone-DSP 时钟生成 sg chunk；
# 3. 保存旧 auto_tct.tbl，安装新表并验证 proc readback；
# 4. auto_tct.tbl 会被已经安装的 bootswitcher autoload 在开机时重新应用。

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot
$ProfilePath = (Resolve-Path -LiteralPath $ProfilePath).Path
$OutputDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $OutputDir))

$RemoteDir = "/data/local/cxd3778gf_tone"
$ToneProc = "/proc/icx_audio_cxd3778gf_data/tct"
$ApplyProc = "/proc/cxd3778gf_tone_apply"
$RemoteStage = "$RemoteDir/etymotic_evo_2flange.tbl"
$RemoteAuto = "$RemoteDir/auto_tct.tbl"
$RemoteBackup = "$RemoteDir/auto_tct.before_etymotic_evo_2flange.tbl"

$BaseBody = Join-Path $OutputDir "zx300a-current-base.body"
$BaseTable = Join-Path $OutputDir "zx300a-current-base.tbl"
$OutputTable = Join-Path $OutputDir "etymotic-evo-2flange-zx300a.tbl"
$SplitDir = Join-Path $OutputDir "chunks"
$PlotDir = Join-Path $OutputDir "plots"
$ReadbackBody = Join-Path $OutputDir "installed-readback.body"
$InputCopy = Join-Path $OutputDir "Etymotic Evo (2-flange eartips) ParametricEq.txt"

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

if (-not (Test-Path -LiteralPath $Adb -PathType Leaf)) { throw "找不到 adb：$Adb" }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "找不到 Python：$Python" }
if (Get-Process -Name python, pythonw -ErrorAction SilentlyContinue) {
    throw "检测到 Python 进程。请先结束所有播放/录音测量进程，再安装 tone table。"
}

New-Item -ItemType Directory -Force -Path $OutputDir, $SplitDir, $PlotDir | Out-Null
Copy-Item -LiteralPath $ProfilePath -Destination $InputCopy -Force

Invoke-Checked $Python "-c" "import pathlib; import sys; sys.path.insert(0, 'tools'); import autoeq_to_cxd3778gf_peq as p; assert p.DEFAULT_TONE_FS_441 == 176400 and p.DEFAULT_TONE_FS_48 == 192000"
Invoke-Adb start-server
Invoke-Adb wait-for-device
Invoke-Adb shell "test -e '$ToneProc' && test -e '$ApplyProc'"
Invoke-Adb shell "mkdir -p '$RemoteDir'; cat '$ToneProc' > '$RemoteDir/etymotic_evo_base.body'"
Invoke-Adb pull "$RemoteDir/etymotic_evo_base.body" $BaseBody

Invoke-Checked $Python "tools\cxd3778gf_tct_tool.py" "add-checksum" $BaseBody $BaseTable
Invoke-Checked $Python "tools\autoeq_to_cxd3778gf_table.py" `
    $InputCopy $OutputTable `
    "--base-table" $BaseTable `
    "--target" "sg" `
    "--filter-strategy" "first" `
    "--max-sections" "5" `
    "--fs441" "$ToneFs441" `
    "--fs48" "$ToneFs48"
Invoke-Checked $Python "tools\cxd3778gf_tct_tool.py" "inspect" $OutputTable
Invoke-Checked $Python "tools\cxd3778gf_tct_tool.py" "split" $OutputTable $SplitDir
Invoke-Checked $Python "tools\plot_cxd3778gf_tct_response.py" `
    "--out-dir" $PlotDir `
    "--chunk-file" "etymotic-evo=$SplitDir\tct_sg.bin" `
    "--fs441" "$ToneFs441" `
    "--fs48" "$ToneFs48"

# 第一次安装时保留旧的持久化表；重复运行不会覆盖这份恢复点。
Invoke-Adb shell "if [ -f '$RemoteAuto' ] && [ ! -f '$RemoteBackup' ]; then cp '$RemoteAuto' '$RemoteBackup'; fi"
Invoke-Adb push $OutputTable $RemoteStage

$LocalMd5 = (Get-FileHash -Algorithm MD5 -LiteralPath $OutputTable).Hash.ToLowerInvariant()
$RemoteMd5Line = (& $Adb shell "md5sum '$RemoteStage'").Trim()
if ($LASTEXITCODE -ne 0) { throw "无法读取远端 MD5" }
$RemoteMd5 = ($RemoteMd5Line -split "\s+")[0].ToLowerInvariant()
if ($LocalMd5 -ne $RemoteMd5) {
    throw "远端 table MD5 不匹配：local=$LocalMd5 remote=$RemoteMd5"
}

# 仅在所有本地生成和远端传输校验通过后，替换持久化表并应用。
Invoke-Adb shell "cp '$RemoteStage' '$RemoteAuto' && chmod 0600 '$RemoteAuto'"
Invoke-Adb shell "cat '$RemoteAuto' > '$ToneProc'"
Invoke-Adb shell "echo table 5 > '$ApplyProc'"
Invoke-Adb shell "cat '$ToneProc' > '$RemoteDir/etymotic_evo_installed_readback.body'"
Invoke-Adb pull "$RemoteDir/etymotic_evo_installed_readback.body" $ReadbackBody

$ExpectedBody = [System.IO.File]::ReadAllBytes($OutputTable)[0..2879]
$ActualBody = [System.IO.File]::ReadAllBytes($ReadbackBody)
if ($ActualBody.Length -ne 2880) { throw "proc readback 长度异常：$($ActualBody.Length)" }
for ($Index = 0; $Index -lt 2880; $Index++) {
    if ($ExpectedBody[$Index] -ne $ActualBody[$Index]) {
        throw "proc readback 在 byte $Index 不匹配"
    }
}

Invoke-Adb shell "md5sum '$RemoteAuto' '$RemoteBackup' 2>/dev/null; grep -n 'CXD3778GF tone table apply support' /system/bin/bootswitcher.sh 2>/dev/null; cat '$ApplyProc'"
Write-Host "安装完成：$OutputTable"
Write-Host "本地 MD5：$LocalMd5"
Write-Host "设备恢复点：$RemoteBackup"
