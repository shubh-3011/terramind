@echo off
title TerraMind - Generate synthetic training data (live)
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind - generate provider-valid synthetic SFT data
echo   (deterministic scaffolder -> prompt/HCL pairs)
echo   Log: C:\Users\shubh\Downloads\terramind\.build\synth-data-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.venv\Scripts\python.exe' -u -m terramind_ml.synth_data --output 'C:\Users\shubh\Downloads\terramind\.build\terramind-synth-sft' --train 8000 --validation 800 --seed 17 *>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\.build\synth-data-log.txt'"

echo.
echo === Synthetic data generation finished (exit %ERRORLEVEL%) ===
pause
