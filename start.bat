@echo off
setlocal
title TEMM - The Completion Runtime
echo =======================================================
echo   AI FLEET OS - Open AI Command Center
echo =======================================================

where python >nul 2>nul
if errorlevel 1 (
  echo Error: Python is not installed or not found in PATH.
  exit /b 1
)

echo [1/3] Verifying Python dependencies...
if exist "requirements-lock-win.txt" (
  python -m pip install --require-hashes -r requirements-lock-win.txt --quiet
) else (
  python -m pip install -r requirements.txt --quiet
)
if errorlevel 1 exit /b %errorlevel%

if not exist "apps\web\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo Error: npm is required because no frontend build exists.
    exit /b 1
  )
  echo [2/3] Building frontend...
  pushd "apps\web"
  call npm ci --silent
  if errorlevel 1 (popd & exit /b %errorlevel%)
  call npm run build
  if errorlevel 1 (popd & exit /b %errorlevel%)
  popd
) else (
  echo [2/3] Frontend bundle ready.
)

if not exist "apps\web\dist\index.html" exit /b 1
echo [3/3] Starting TEMM...
python run.py
exit /b %errorlevel%
