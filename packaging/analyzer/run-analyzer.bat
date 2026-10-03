@echo off
rem Starts the TerraMind analyzer with the bundled portable Python.
rem Environment variables (model path, threads, GGUF options, ...) are inherited
rem from the parent TerraMind.bat launcher.
cd /d "%~dp0"

rem Keep the bundled runtime self-contained: never read the user's site-packages
rem and never write .pyc files back into the bundle.
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"

if not exist "%~dp0runtime\python.exe" (
  echo ERROR: bundled Python runtime not found at "%~dp0runtime\python.exe".
  echo Re-extract the TerraMind ZIP; the analyzer/ folder looks incomplete.
  pause
  exit /b 1
)

"%~dp0runtime\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
