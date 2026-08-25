param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\TEMM",
    [string]$DataRoot = "$env:LOCALAPPDATA\TEMM Data",
    [switch]$PurgeData
)

$ErrorActionPreference = "Stop"
$arguments = @((Join-Path $PSScriptRoot "windows_installer.py"), "uninstall", "--install-root", $InstallRoot, "--data-root", $DataRoot)
if ($PurgeData) { $arguments += "--purge-data" }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "Uninstall failed." }
