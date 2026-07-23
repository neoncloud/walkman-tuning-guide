param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("a", "zx", "wm")]
    [string]$DeviceClass,

    [string]$Input,
    [string]$Table,
    [string]$Target = "sg",
    [ValidateSet("first", "largest", "wide", "greedy", "best")]
    [string]$FilterStrategy = "best",
    [ValidateSet("1", "2", "3", "4", "5")]
    [string]$MaxSections = "5",
    [string]$Adb = $env:ADB,
    [string]$Python = $env:PYTHON
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param([string]$Path)
    return (Resolve-Path -LiteralPath $Path).Path
}

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
        $Input = Need-File $Input "-Input AutoEq text"
        if ($Target -notin @("nh", "ng", "nnw500", "nnw750", "nnc31", "sg", "snw500", "snw750", "snc31")) {
            throw "Invalid target: $Target"
        }

        $procNode = "/proc/icx_audio_cxd3778gf_data/tct_$Target"
        $backupDir = Join-Path $RepoRoot "backups\live"
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        $localBackup = Join-Path $backupDir "tct_$Target.bin"
        $localBlob = Join-Path $backupDir "peq_$Target.proc"
        $localReadback = Join-Path $backupDir "tct_$Target.readback.bin"
        $remoteDir = "/data/local/cxd3778gf_tone"
        $remoteBackup = "$remoteDir/tct_$Target.backup.body"
        $remoteBlob = "$remoteDir/peq_$Target.proc"

        Invoke-Adb start-server
        Invoke-Adb wait-for-device
        Invoke-Adb shell "mkdir -p '$remoteDir'; cat '$procNode' > '$remoteBackup'"
        if (Test-Path -LiteralPath $localBackup) {
            Write-Host "Keeping existing local backup: $localBackup"
            Invoke-Adb pull $remoteBackup (Join-Path $backupDir "tct_$Target.current-before-apply.bin")
        } else {
            Invoke-Adb pull $remoteBackup $localBackup
            Write-Host "Created local backup: $localBackup"
        }

        & $Python (Join-Path $RepoRoot "tools\autoeq_to_cxd3778gf_peq.py") $Input $localBlob `
            --filter-strategy $FilterStrategy --max-sections $MaxSections
        if ($LASTEXITCODE -ne 0) { throw "PEQ generation failed" }

        Invoke-Adb push $localBlob $remoteBlob
        Invoke-Adb shell "cat '$remoteBlob' > '$procNode'"
        Invoke-Adb shell "cat '$procNode' > '$remoteDir/tct_$Target.readback.body'"
        Invoke-Adb pull "$remoteDir/tct_$Target.readback.body" $localReadback

        $expected = [System.IO.File]::ReadAllBytes($localBlob)[0..319]
        $actual = [System.IO.File]::ReadAllBytes($localReadback)
        if ($actual.Length -ne 320) { throw "Unexpected readback size: $($actual.Length)" }
        for ($i = 0; $i -lt 320; $i++) {
            if ($expected[$i] -ne $actual[$i]) {
                throw "Readback mismatch at byte $i"
            }
        }
        Write-Host "Applied PEQ to $procNode and verified readback."
        Write-Host "Restore with: scripts\restore_stock_tone_table.ps1 -DeviceClass a -Target $Target"
    }

    { $_ -in @("zx", "wm") } {
        $Table = Need-File $Table "-Table full tone table"
        $remote = "/data/local/cxd3778gf_tone/manual_tct.tbl"

        Invoke-Adb start-server
        Invoke-Adb wait-for-device
        Invoke-Adb shell "mkdir -p /data/local/cxd3778gf_tone"
        Invoke-Adb push $Table $remote
        Invoke-Adb shell "cat '$remote' > /proc/icx_audio_cxd3778gf_data/tct"
        Invoke-Adb shell "echo apply > /proc/cxd3778gf_tone_apply"
        Invoke-Adb shell "cat /proc/cxd3778gf_tone_apply"
    }
}
