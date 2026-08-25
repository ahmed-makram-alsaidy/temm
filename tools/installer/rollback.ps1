param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\TEMM",
    [string]$DataRoot = "$env:LOCALAPPDATA\TEMM Data"
)

$ErrorActionPreference = "Stop"
& python (Join-Path $PSScriptRoot "windows_installer.py") rollback --install-root $InstallRoot --data-root $DataRoot
if ($LASTEXITCODE -ne 0) { throw "Rollback failed." }
