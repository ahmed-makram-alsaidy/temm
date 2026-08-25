param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Output = "dist\AI-Fleet-OS-$Version.zip"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$frontend = Join-Path $root "apps\web\dist\index.html"
if (-not (Test-Path -LiteralPath $frontend -PathType Leaf)) {
    throw "Frontend production build is missing. Run npm run build in apps/web first."
}
$outputPath = if ([System.IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $root $Output }
$outputParent = Split-Path -Parent $outputPath
if (-not (Test-Path -LiteralPath $outputParent)) {
    New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
}
& python (Join-Path $PSScriptRoot "windows_installer.py") package --source $root --output $outputPath --version $Version --include LICENSE dependency-licenses.json start.bat start.ps1 run.py requirements-lock-win.txt core apps\web\dist
if ($LASTEXITCODE -ne 0) {
    throw "Windows package build failed."
}
