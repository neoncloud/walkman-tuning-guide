param(
    [string]$Firmware = $env:FIRMWARE,
    [string]$UpgTool = $env:UPGTOOL,
    [string]$OutDir,
    [string]$UnpackedDir = $env:UNPACKED_DIR,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Find-FirstFile {
    param(
        [string[]]$Roots,
        [string]$Pattern
    )
    foreach ($root in $Roots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) {
            continue
        }
        $hit = Get-ChildItem -LiteralPath $root -Filter $Pattern -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) {
            return $hit.FullName
        }
    }
    return $null
}

function Read-PathOrExit {
    param(
        [string]$Prompt,
        [string]$Current
    )
    if ($Current -and (Test-Path -LiteralPath $Current)) {
        return (Resolve-Path -LiteralPath $Current).Path
    }
    $value = Read-Host $Prompt
    if (-not $value -or -not (Test-Path -LiteralPath $value)) {
        throw "Path not found: $value"
    }
    return (Resolve-Path -LiteralPath $value).Path
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) {
    $OutDir = Join-Path $RepoRoot "out\adb-unlock"
}
$WorkDir = Join-Path $OutDir "work"
$PatchedDir = Join-Path $OutDir "patched"

if (-not $Firmware) {
    $Firmware = Find-FirstFile -Roots @($PWD.Path, "$env:USERPROFILE\Downloads") -Pattern "*.UPG"
}
if (-not $UpgTool) {
    $UpgTool = Find-FirstFile -Roots @($PWD.Path, "$env:USERPROFILE\Downloads") -Pattern "upgtool*.exe"
}

$Firmware = Read-PathOrExit -Prompt "Firmware package path (.UPG)" -Current $Firmware
$UpgTool = Read-PathOrExit -Prompt "upgtool executable path" -Current $UpgTool

Write-Host "Firmware: $Firmware"
Write-Host "upgtool:  $UpgTool"
Write-Host "work:     $WorkDir"
Write-Host "patched:  $PatchedDir"
Write-Host ("mode:     " + ($(if ($Apply) { "apply" } else { "dry-run" })))

if (-not $Apply) {
    Write-Host ""
    Write-Host "Dry-run only. Re-run with -Apply after checking the paths."
    Write-Host "The original firmware will not be modified in place."
    exit 0
}

New-Item -ItemType Directory -Force -Path $WorkDir, $PatchedDir | Out-Null
Copy-Item -LiteralPath $Firmware -Destination (Join-Path $WorkDir "original.UPG") -Force

if (-not $UnpackedDir) {
    $UnpackedDir = Join-Path $WorkDir "unpacked"
}

if (-not (Test-Path -LiteralPath $UnpackedDir)) {
    Write-Host ""
    Write-Host "Next step:"
    Write-Host "  1. Use the Windows firmware unpacker/upgtool to unpack:"
    Write-Host "       $(Join-Path $WorkDir 'original.UPG')"
    Write-Host "  2. Put the unpacked firmware tree at:"
    Write-Host "       $UnpackedDir"
    Write-Host "  3. Re-run this script with -Apply."
    Write-Host ""
    Write-Host "Sony's official updater is Windows-only. Linux workflows usually rely on"
    Write-Host "Rockbox/community reverse-engineered tools, so this PowerShell path is the"
    Write-Host "recommended firmware-patching entry point for normal users."
    exit 0
}

$patterns = @("adbd", "persist.sys.usb", "setprop", "install", "update")
$candidates = Get-ChildItem -LiteralPath $UnpackedDir -File -Recurse -ErrorAction SilentlyContinue |
    Where-Object {
        $path = $_.FullName
        try {
            $text = Get-Content -LiteralPath $path -Raw -ErrorAction Stop
            foreach ($pattern in $patterns) {
                if ($text -match [regex]::Escape($pattern)) {
                    return $true
                }
            }
        } catch {
            return $false
        }
        return $false
    } |
    Select-Object -First 20

if (-not $candidates -or $candidates.Count -eq 0) {
    throw "No candidate installer script found under $UnpackedDir"
}

Write-Host "Candidate installer scripts:"
for ($i = 0; $i -lt $candidates.Count; $i++) {
    Write-Host ("  [{0}] {1}" -f $i, $candidates[$i].FullName)
}

$choiceText = Read-Host "Patch which script? [0]"
if (-not $choiceText) {
    $choice = 0
} else {
    $choice = [int]$choiceText
}
if ($choice -lt 0 -or $choice -ge $candidates.Count) {
    throw "Invalid choice: $choice"
}

$candidate = $candidates[$choice].FullName
$text = Get-Content -LiteralPath $candidate -Raw
$begin = "# Walkman tuning guide ADB unlock begin"
$end = "# Walkman tuning guide ADB unlock end"
$block = @"

$begin
setprop persist.service.adb.enable 1
setprop persist.sys.usb.config adb
start adbd
$end
"@

if ($text -notlike "*$begin*") {
    Set-Content -LiteralPath $candidate -Value ($text.TrimEnd() + $block + "`r`n") -Encoding UTF8
}

Write-Host ""
Write-Host "Patched candidate installer script:"
Write-Host "  $candidate"
Write-Host ""
Write-Host "Now repack the unpacked firmware tree:"
Write-Host "  $UnpackedDir"
Write-Host ""
Write-Host "Write the repacked firmware into:"
Write-Host "  $PatchedDir"
Write-Host ""
Write-Host "Then replace the firmware file used by Sony's official Windows installer"
Write-Host "with the patched copy. Keep the original package untouched for recovery."
