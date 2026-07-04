@echo off
setlocal

set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%patch_firmware_adb_unlock.ps1" %*
exit /b %ERRORLEVEL%
