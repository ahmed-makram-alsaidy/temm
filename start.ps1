$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Run from this script's folder so relative paths work no matter where the user starts it.
$Root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location -LiteralPath $Root

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  TEMM - The Completion Runtime" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan

# The Windows dependency lock (requirements-lock-win.txt) is hash-pinned for
# CPython 3.12 x64. Prefer the `py` launcher's 3.12 interpreter, then plain `python`,
# and fail with an actionable message instead of a cryptic hash error on 3.11/3.13.
$script:PythonArgs = $null
$candidates = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += ,@("py", "-3.12") }
if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += ,@("python") }
foreach ($candidate in $candidates) {
    $probe = @()
    if ($candidate.Count -gt 1) { $probe += $candidate[1] }
    $probe += @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
    $reported = & $candidate[0] @probe 2>$null
    if ($LASTEXITCODE -eq 0 -and ("$reported".Trim() -like "3.12*")) {
        $script:PythonArgs = $candidate
        break
    }
}
if (-not $script:PythonArgs) {
    throw "Python 3.12 (64-bit) is required: the pinned Windows dependency set is built for CPython 3.12 x64. Install it from https://www.python.org/downloads/ and re-run .\start.ps1"
}

function Invoke-Python {
    $rest = @()
    if ($script:PythonArgs.Count -gt 1) { $rest = $script:PythonArgs[1..($script:PythonArgs.Count - 1)] }
    & $script:PythonArgs[0] @rest @args
}

# Install into a project-local virtualenv so the user's global Python stays untouched.
$venvDir = Join-Path $Root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "[1/4] Creating local virtual environment (.venv)..." -ForegroundColor Cyan
    Invoke-Python -m venv ".venv"
    if ($LASTEXITCODE -ne 0) { throw "Could not create the .venv virtual environment." }
} else {
    Write-Host "[1/4] Using existing .venv environment." -ForegroundColor Cyan
}

Write-Host "[2/4] Installing pinned backend dependencies..." -ForegroundColor Cyan
if (Test-Path -LiteralPath (Join-Path $Root "requirements-lock-win.txt")) {
    & $venvPython -m pip install --require-hashes -r requirements-lock-win.txt --quiet
} else {
    & $venvPython -m pip install -r requirements.txt --quiet
}
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }

if (-not (Test-Path -LiteralPath (Join-Path $Root "apps\web\dist\index.html"))) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "Node.js 22 + npm are required because no frontend production build exists. Install Node 22 from https://nodejs.org and re-run .\start.ps1"
    }
    Write-Host "[3/4] Building Command Center Web Interface..." -ForegroundColor Cyan
    Push-Location (Join-Path $Root "apps\web")
    try {
        & npm ci --silent
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[3/4] Web Command Center bundle ready." -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath (Join-Path $Root "apps\web\dist\index.html"))) {
    throw "Frontend production bundle is unavailable."
}

Write-Host "[4/4] Starting TEMM at http://localhost:8787 ..." -ForegroundColor Green
& $venvPython "run.py"
if ($LASTEXITCODE -ne 0) { throw "TEMM exited with code $LASTEXITCODE." }
