@echo off
title TerraMind - Model Evaluation (live progress)
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TERRAMIND_HF_MODEL_PATH=C:\Users\shubh\Downloads\terramind\.build\terramind-qwen2.5-coder-1.5b-terraform-merged
set TERRAMIND_HF_MAX_NEW_TOKENS=1024
set TERRAMIND_EVAL_COUNT=8
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind - held-out generation evaluation (HCL parse rate)
echo   Live progress below. A copy is saved to:
echo     C:\Users\shubh\Downloads\terramind\.build\eval-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& 'C:\Users\shubh\Downloads\terramind\.build\sft-train-venv\Scripts\python.exe' -u 'C:\Users\shubh\Downloads\terramind\scripts\eval_model.py' 2>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\.build\eval-log.txt'"

echo.
echo === Evaluation finished (exit %ERRORLEVEL%) ===
pause
