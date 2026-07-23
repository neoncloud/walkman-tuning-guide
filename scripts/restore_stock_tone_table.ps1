param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("a", "zx", "wm")]
    [string]$DeviceClass,

    [string]$Target = "sg",
    [string]$StockTable,
    [string]$Adb = $env:ADB,
    [string]$Python = $env:PYTHON
)

$ErrorActionPreference = "Stop"

function Invoke-Adb {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & $Adb @Args
    if ($LASTEXITCODE -ne 0) {
        throw "adb failed: $Adb $($Args -join ' ')"
    }
}

function Need-File {
    param([string]$Path, [string]$Label)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $Adb) {
    $found = Get-Command adb.exe -ErrorAction SilentlyContinue
    if ($found) { $Adb = $found.Source }
}
if (-not $Python) {
    $found = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $found) { $found = Get-Command python -ErrorAction SilentlyContinue }
    if ($found) { $Python = $found.Source }
}
if (-not $Adb) { throw "adb.exe not found. Pass -Adb C:\path\to\adb.exe or set ADB." }
if (-not $Python) { throw "python.exe not found. Pass -Python C:\path\to\python.exe or set PYTHON." }

Set-Location $RepoRoot

switch ($DeviceClass) {
    "a" {
        if ($Target -notin @("nh", "ng", "nnw500", "nnw750", "nnc31", "sg", "snw500", "snw750", "snc31")) {
            throw "Invalid target: $Target"
        }
        $backupBody = Join-Path $RepoRoot "backups\live\tct_$Target.bin"
        $backupProc = Join-Path $RepoRoot "backups\live\tct_$Target.backup.proc"
        $readback = Join-Path $RepoRoot "backups\live\tct_$Target.restore-readback.bin"
        $backupBody = Need-File $backupBody "A-series backup body"

        & $Python (Join-Path $RepoRoot "tools\cxd3778gf_tct_tool.py") add-checksum $backupBody $backupProc
        if ($LASTEXITCODE -ne 0) { throw "Checksum generation failed" }

        $procNode = "/proc/icx_audio_cxd3778gf_data/tct_$Target"
        $remoteDir = "/data/local/cxd3778gf_tone"
        $remoteBackup = "$remoteDir/tct_$Target.backup.proc"
        Invoke-Adb start-server
        Invoke-Adb wait-for-device
        Invoke-Adb shell "mkdir -p '$remoteDir'"
        Invoke-Adb push $backupProc $remoteBackup
        Invoke-Adb shell "cat '$remoteBackup' > '$procNode'"
        Invoke-Adb shell "cat '$procNode' > '$remoteDir/tct_$Target.restore-readback.body'"
        Invoke-Adb pull "$remoteDir/tct_$Target.restore-readback.body" $readback

        $expected = [System.IO.File]::ReadAllBytes($backupBody)
        $actual = [System.IO.File]::ReadAllBytes($readback)
        if ($expected.Length -ne $actual.Length) { throw "Restore readback size mismatch" }
        for ($i = 0; $i -lt $expected.Length; $i++) {
            if ($expected[$i] -ne $actual[$i]) { throw "Restore readback mismatch at byte $i" }
        }
        Write-Host "Restored $procNode from $backupBody and verified readback."
    }

    { $_ -in @("zx", "wm") } {
        if (-not $StockTable) {
            $StockTable = Join-Path $RepoRoot "backups\tc_127x.tbl"
        }
        $StockTable = Need-File $StockTable "ZX/WM stock full table"
        $remote = "/data/local/cxd3778gf_tone/stock_tct.tbl"
        $readback = Join-Path $RepoRoot "backups\proc_tct_after_restore.bin"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $readback) | Out-Null

        Invoke-Adb start-server
        Invoke-Adb wait-for-device
        Invoke-Adb shell "mkdir -p /data/local/cxd3778gf_tone"
        Invoke-Adb push $StockTable $remote
        Invoke-Adb shell "cat '$remote' > /proc/icx_audio_cxd3778gf_data/tct"
        Invoke-Adb shell "echo apply > /proc/cxd3778gf_tone_apply"
        Invoke-Adb shell "cat /proc/cxd3778gf_tone_apply"
        Invoke-Adb pull "/proc/icx_audio_cxd3778gf_data/tct" $readback
        Write-Host "Restored stock table and refreshed tone RAM."
    }
}
