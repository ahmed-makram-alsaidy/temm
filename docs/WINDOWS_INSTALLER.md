# Windows Installer Release

## Build pipeline

### Prerequisites

- Inno Setup 6.x installed (`iscc.exe` available)
- Python 3.12 with locked dependencies
- Node.js 22 with `npm ci` completed in `apps/web`
- Frontend production build completed (`npm run build`)

### Steps

```powershell
# 1. Build frontend
Set-Location apps/web
npm ci
npm run build
Set-Location ../..

# 2. Build runtime package
$version = "0.1.0"
.\tools\installer\build-windows-package.ps1 -Version $version

# 3. Extract runtime package to staging
$staging = "dist\runtime"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
Expand-Archive "dist\TEMM-$version.zip" -DestinationPath $staging

# 4. Compile installer (requires Inno Setup)
iscc /Qp "tools\installer\temm-setup.iss"
# Output: dist\Output\TEMM-Setup-0.1.0-x64.exe
```

### Code signing (optional, requires certificate)

```powershell
# Sign the installer after compilation
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
  /f path\to\certificate.pfx /p $env:CERT_PASSWORD `
  "dist\Output\TEMM-Setup-0.1.0-x64.exe"
```

Code signing is optional during development. Unsigned installers will trigger Windows SmartScreen warnings. A real owner-controlled code-signing certificate is required before public signed release.

## Clean-machine verification procedure

### Requirements

- Clean Windows 10/11 64-bit VM or Windows Sandbox
- No pre-existing Python, Node.js, or TEMM installation
- Network access for initial Python/pip dependency installation

### Test matrix

| Step | Command/action | Expected |
|---:|---|---|
| 1 | Run `TEMM-Setup-x64.exe` | Installer completes without error |
| 2 | Verify `%LOCALAPPDATA%\TEMM\versions\0.1.0\start.bat` exists | File present |
| 3 | Verify `%LOCALAPPDATA%\TEMM\TEMM.cmd` exists | Launcher present |
| 4 | Verify `%LOCALAPPDATA%\TEMM Data` directory created | Directory exists |
| 5 | Verify `%LOCALAPPDATA%\TEMM\install-state.json` has correct version | `current_version: "0.1.0"` |
| 6 | Run `%LOCALAPPDATA%\TEMM\TEMM.cmd` | Server starts, browser opens |
| 7 | Navigate to `http://localhost:8787/health/ready` | HTTP 200 |
| 8 | Verify Start Menu shortcut exists | "TEMM" group present |
| 9 | Run uninstaller from Add/Remove Programs | Uninstall completes |
| 10 | Verify `%LOCALAPPDATA%\TEMM` is removed | Directory absent |
| 11 | Verify `%LOCALAPPDATA%\TEMM Data` is preserved | Directory still present (data preserved) |

### Automation script (run inside clean VM)

```powershell
$ErrorActionPreference = "Stop"
$installer = "\\host-share\TEMM-Setup-0.1.0-x64.exe"
$installRoot = "$env:LOCALAPPDATA\TEMM"
$dataRoot = "$env:LOCALAPPDATA\TEMM Data"

# Install silently
& $installer /VERYSILENT /NORESTART /LOG="$env:TEMP\temm-install.log"
if ($LASTEXITCODE -ne 0) { throw "Install failed with exit code $LASTEXITCODE" }

# Verify files
if (-not (Test-Path "$installRoot\versions\0.1.0\start.bat")) { throw "Runtime missing" }
if (-not (Test-Path "$installRoot\TEMM.cmd")) { throw "Launcher missing" }
if (-not (Test-Path $dataRoot)) { throw "Data root missing" }

$state = Get-Content "$installRoot\install-state.json" | ConvertFrom-Json
if ($state.current_version -ne "0.1.0") { throw "Version mismatch" }

Write-Host "INSTALL VERIFIED" -ForegroundColor Green

# Uninstall silently
$uninstaller = Get-ChildItem "$installRoot\unins*.exe" | Select-Object -First 1
& $uninstaller.FullName /VERYSILENT /NORESTART
Start-Sleep -Seconds 5

if (Test-Path $installRoot) { throw "Install root not removed" }
if (-not (Test-Path $dataRoot)) { throw "Data root was deleted (should be preserved)" }

Write-Host "UNINSTALL VERIFIED — data preserved" -ForegroundColor Green
```

## Current status

- Inno Setup script: **ready** (`tools/installer/temm-setup.iss`)
- Runtime package tooling: **ready** (`tools/installer/build-windows-package.ps1`)
- Deterministic ZIP packaging: **verified** (test_windows_installer passes)
- Code signing: **blocked** (no owner certificate)
- Clean-VM verification: **blocked** (requires `iscc.exe` and clean Windows VM)
- Inno Setup compiler: **not installed locally** (`iscc` not found)
