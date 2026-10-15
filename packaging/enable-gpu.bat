@echo off
rem Adds CUDA (GPU) acceleration to the bundled portable analyzer.
rem
rem The shipped beta bundle carries the CPU llama-cpp-python wheel, so it runs on
rem any PC. This script swaps that single wheel for the CUDA build inside the
rem bundle's own runtime, after which TerraMind.bat offloads all layers to the GPU
rem automatically whenever an NVIDIA GPU is present.
setlocal
title TerraMind - enable GPU acceleration
cd /d "%~dp0"

echo ============================================================
echo   TerraMind - add CUDA (GPU) acceleration
echo ============================================================
echo.
echo Downloads a CUDA build of llama-cpp-python into the bundled runtime.
echo It is large (~1-2 GB) and only useful with an NVIDIA GPU + recent driver.
echo The CPU install is left intact if anything fails.
echo.

set "ANALYZER=%~dp0analyzer"
if not exist "%ANALYZER%\runtime\python.exe" (
  echo ERROR: bundled Python runtime not found at "%ANALYZER%\runtime\python.exe".
  echo Run this script from the unzipped TerraMind folder.
  pause
  exit /b 1
)

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo WARNING: nvidia-smi was not found on PATH. Installing anyway; if no NVIDIA
  echo          GPU is present, TerraMind falls back to the CPU at launch.
  echo.
)

set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"

echo Installing the CUDA wheel. This can take several minutes...
"%ANALYZER%\runtime\python.exe" -m pip install --upgrade --no-cache-dir ^
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 ^
  llama-cpp-python

if errorlevel 1 (
  echo.
  echo Trying the cu122 index as a fallback...
  "%ANALYZER%\runtime\python.exe" -m pip install --upgrade --no-cache-dir ^
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu122 ^
    llama-cpp-python
)

set "CUDA_DLL="
for %%F in ("%ANALYZER%\runtime\Lib\site-packages\llama_cpp\lib\ggml-cuda*.dll") do set "CUDA_DLL=%%F"

echo.
if defined CUDA_DLL (
  echo SUCCESS: CUDA libraries are now bundled:
  echo   %CUDA_DLL%
  echo.
  echo Start TerraMind with TerraMind.bat; it will detect the GPU and offload the model.
) else (
  echo The CUDA libraries were not found after install. TerraMind will keep using the CPU.
  echo Check your internet connection and that the wheel index is reachable.
)
pause
exit /b 0
