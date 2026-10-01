@echo off
title TerraMind - GGUF export (live progress)
set TERRAMIND_LLAMA_CPP_DIR=C:\Users\shubh\Downloads\terramind\.build\tools\llama-cpp
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind - convert merged model to Q4_K_M GGUF
echo   Live progress below. A copy is saved to:
echo     C:\Users\shubh\Downloads\terramind\.build\export-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& 'C:\Users\shubh\Downloads\terramind\.build\sft-train-venv\Scripts\python.exe' -u -m terramind_ml.export_gguf --merged 'C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-1.5b-terraform-merged' --out-dir 'C:\Users\shubh\Downloads\terramind\.build\terramind-gguf' --quant Q4_K_M --base-model 'Qwen/Qwen2.5-Coder-1.5B-Instruct' --base-revision '2e1fd397ee46e1388853d2af2c993145b0f1098a' --license 'Apache-2.0' 2>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\.build\export-log.txt'"

echo.
echo === Export finished (exit %ERRORLEVEL%) ===
pause
