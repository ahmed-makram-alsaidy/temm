@echo off
setlocal
title TEMM - The Completion Runtime

rem Run from this script's folder regardless of the caller's working directory.
pushd "%~dp0"

echo =======================================================
echo   TEMM - The Completion Runtime
echo =======================================================

rem The Windows dependency lock is hash-pinned for CPython 3.12 x64.
set "PYTHONCMD="
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 (
  set "PYTHONARGS=-3.12"
  goto :have_python
)
python -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>nul
if not errorlevel 1 (
  set "PYTHONARGS="
  goto :have_python
)
echo Error: Python 3.12 (64-bit) is required - the pinned Windows dependency set
echo is built for CPython 3.12 x64. Install it from https://www.python.org/downloads/
echo and re-run start.bat
popd
exit /b 1

:have_python
if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating local virtual environment ^(.venv^)...
  py %PYTHONARGS% -m venv .venv || python %PYTHONARGS% -m venv .venv
  if errorlevel 1 (
    echo Error: could not create the .venv virtual environment.
    popd
    exit /b 1
  )
) else (
  echo [1/4] Using existing .venv environment.
)
set "RUNPYTHON=.venv\Scripts\python.exe"

echo [2/4] Installing pinned backend dependencies...
if exist "requirements-lock-win.txt" (
  "%RUNPYTHON%" -m pip install --require-hashes -r requirements-lock-win.txt --quiet
) else (
  "%RUNPYTHON%" -m pip install -r requirements.txt --quiet
)
if errorlevel 1 (
  echo Error: Python dependency installation failed.
  popd
  exit /b 1
)

if not exist "apps\web\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo Error: Node.js 22 + npm are required because no frontend build exists.
    echo Install Node 22 from https://nodejs.org and re-run start.bat
    popd
    exit /b 1
  )
  echo [3/4] Building frontend...
  pushd "apps\web"
  call npm ci --silent
  if errorlevel 1 (popd & popd & exit /b 1)
  call npm run build
  if errorlevel 1 (popd & popd & exit /b 1)
  popd
) else (
  echo [3/4] Frontend bundle ready.
)

if not exist "apps\web\dist\index.html" (
  echo Error: frontend production bundle is unavailable.
  popd
  exit /b 1
)
echo [4/4] Starting TEMM at http://localhost:8787 ...
"%RUNPYTHON%" run.py
set "EXITCODE=%errorlevel%"
popd
exit /b %EXITCODE%
