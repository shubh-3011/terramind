@echo off
setlocal
title TerraMind Beta 1
set "ROOT=%~dp0"
set "ANALYZER=%ROOT%analyzer"
set "MODELDIR=%USERPROFILE%\.terramind\models"
set "MODEL=%MODELDIR%\terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf"
rem Single source of truth for the model download. Hosted on Hugging Face so it is
rem CDN-backed, resumable and versioned; curl's -C - flag resumes a partial download.
set "MODEL_URL=https://huggingface.co/shubh-3011/terramind-qwen2.5-coder-1.5b-terraform/resolve/main/terramind-qwen2.5-coder-v2-merged-Q4_K_M.gguf"

echo ============================================================
echo   TerraMind Beta 1
echo   A local Terraform assistant for your desktop.
echo ============================================================
echo.

if not exist "%MODELDIR%" mkdir "%MODELDIR%" >nul 2>&1

rem [1/3] Fetch the ~940 MB GGUF model once. It lives outside the app folder so
rem unzipping a new build never re-downloads it.
if not exist "%MODEL%" (
  echo [1/3] First run: downloading the local AI model ^(~940 MB, one time only^)
  echo       Saving to: %MODEL%
  echo.
  curl.exe -L --retry 3 --retry-delay 2 -C - -o "%MODEL%" "%MODEL_URL%"
  echo.
  if not exist "%MODEL%" (
    echo ERROR: the model download failed. Check your internet connection and run TerraMind.bat again.
    pause
    exit /b 1
  )
) else (
  echo [1/3] Local model found.
)

rem Point the analyzer at the downloaded model. The beta ships a CPU-only
rem llama-cpp-python build, so no layers are offloaded to a GPU.
set "PYTHONNOUSERSITE=1"
set "TERRAMIND_MODELS_DIR=%MODELDIR%"
set "TERRAMIND_GGUF_MODEL=%MODEL%"
set "TERRAMIND_GGUF_N_GPU_LAYERS=0"
set "TERRAMIND_GGUF_N_CTX=8192"
set "TERRAMIND_GGUF_MAX_TOKENS=2048"
set "TERRAMIND_GGUF_REPEAT_PENALTY=1.2"
set "TERRAMIND_GGUF_TEMPERATURE=0.1"

rem [2/3] Start the bundled analyzer in a minimized window, then poll /health
rem until it answers (up to ~60s) before opening the app.
echo [2/3] Starting the TerraMind analysis service...
start "TerraMind Analyzer" /min "%ANALYZER%\run-analyzer.bat"
set /a tries=0
:waitloop
curl.exe -sf -o nul http://127.0.0.1:8000/health && goto ready
set /a tries+=1
if %tries% GEQ 60 goto notready
timeout /t 1 /nobreak >nul
goto waitloop

:notready
echo       NOTE: the analyzer did not respond in time.
echo       TerraMind will still open; analysis and AI features may be unavailable.
goto launch

:ready
echo       Analysis service is ready at http://127.0.0.1:8000

:launch
rem [3/3] Open the desktop app.
echo [3/3] Opening TerraMind...
start "" "%ROOT%TerraMind.exe"
echo.
echo   TerraMind is running.
echo   The analysis service runs in the minimized "TerraMind Analyzer" window.
echo   Close that window to stop the service.
echo.
timeout /t 10 /nobreak >nul
exit /b 0
