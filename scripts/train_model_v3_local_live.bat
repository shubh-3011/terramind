@echo off
title TerraMind v3 - Qwen2.5-Coder-1.5B training (live progress)
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\shubh\Downloads\terramind\scripts\train_model_v3_local.ps1"
echo.
echo === window finished (exit %ERRORLEVEL%) ===
pause
