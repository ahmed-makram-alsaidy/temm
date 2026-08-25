$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  AI FLEET OS - Open AI Command Center" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is not installed or not found in PATH."
}

Write-Host "[1/3] Verifying Python backend dependencies..." -ForegroundColor Cyan
if (Test-Path -LiteralPath "requirements-lock-win.txt") {
    & python -m pip install --require-hashes -r requirements-lock-win.txt --quiet
} else {
    & python -m pip install -r requirements.txt --quiet
}
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

if (-not (Test-Path -LiteralPath "apps\web\dist\index.html")) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "Node.js/npm is required because no frontend production build exists."
    }
    Write-Host "[2/3] Building Command Center Web Interface..." -ForegroundColor Cyan
    Push-Location "apps\web"
    try {
        & npm ci --silent
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[2/3] Web Command Center bundle ready." -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath "apps\web\dist\index.html")) {
    throw "Frontend production bundle is unavailable."
}

Write-Host "[3/3] Starting TEMM..." -ForegroundColor Green
& python run.py
if ($LASTEXITCODE -ne 0) { throw "TEMM exited with code $LASTEXITCODE." }
