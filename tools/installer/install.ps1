param(
    [Parameter(Mandatory = $true)][string]$Package,
    [Parameter(Mandatory = $true)][string]$Sha256,
    [string]$InstallRoot = "$env:LOCALAPPDATA\TEMM",
    [string]$DataRoot = "$env:LOCALAPPDATA\TEMM Data"
)

$ErrorActionPreference = "Stop"
& python (Join-Path $PSScriptRoot "windows_installer.py") install --package $Package --sha256 $Sha256 --install-root $InstallRoot --data-root $DataRoot
if ($LASTEXITCODE -ne 0) { throw "Installation failed." }
