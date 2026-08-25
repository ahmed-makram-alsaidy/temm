param(
    [int]$Port = 8850,
    [string]$OutputRoot = "$env:TEMP\ai-fleet-browser-gates"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$browsers = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$browser = $browsers | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $browser) { throw "Chrome or Edge is required for browser quality gates." }

$dataRoot = Join-Path $OutputRoot "data"
$oldPort = $env:AI_FLEET_PORT
$oldBrowser = $env:AI_FLEET_NO_BROWSER
$oldData = $env:AI_FLEET_DATA_DIR
$env:AI_FLEET_PORT = "$Port"
$env:AI_FLEET_NO_BROWSER = "1"
$env:AI_FLEET_DATA_DIR = $dataRoot
$server = $null

try {
    if (Test-Path -LiteralPath $OutputRoot) { Remove-Item -LiteralPath $OutputRoot -Recurse -Force }
    New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
    $server = Start-Process python -ArgumentList @("run.py") -PassThru -WindowStyle Hidden -WorkingDirectory $root
    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health/ready" -TimeoutSec 1
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw "Browser gate server did not become ready." }

    $url = "http://127.0.0.1:$Port"
    & python (Join-Path $PSScriptRoot "responsive_smoke.py") --chrome $browser --url $url --language en --output (Join-Path $OutputRoot "screens-en") --report (Join-Path $OutputRoot "responsive-en.json")
    if ($LASTEXITCODE -ne 0) { throw "English responsive browser gate failed." }
    & python (Join-Path $PSScriptRoot "responsive_smoke.py") --chrome $browser --url $url --language ar --output (Join-Path $OutputRoot "screens-ar") --report (Join-Path $OutputRoot "responsive-ar.json")
    if ($LASTEXITCODE -ne 0) { throw "Arabic responsive browser gate failed." }
    & python (Join-Path $PSScriptRoot "contrast_smoke.py") --chrome $browser --url $url --report (Join-Path $OutputRoot "contrast.json")
    if ($LASTEXITCODE -ne 0) { throw "Contrast browser gate failed." }
    & python (Join-Path $PSScriptRoot "keyboard_smoke.py") --chrome $browser --url $url --report (Join-Path $OutputRoot "keyboard.json")
    if ($LASTEXITCODE -ne 0) { throw "Keyboard browser gate failed." }
    & python (Join-Path $PSScriptRoot "ax_smoke.py") --chrome $browser --url $url --report (Join-Path $OutputRoot "accessibility-tree.json")
    if ($LASTEXITCODE -ne 0) { throw "Accessibility tree browser gate failed." }
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    $env:AI_FLEET_PORT = $oldPort
    $env:AI_FLEET_NO_BROWSER = $oldBrowser
    $env:AI_FLEET_DATA_DIR = $oldData
}
