@echo off
rem Provider-validity eval for a specific GGUF model.
rem   Usage: eval_provider_model_live.bat  <model.gguf>  <log.txt>
title TerraMind - provider eval
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TERRAMIND_GENERATION_ENGINE=gguf
set TERRAMIND_GGUF_MODEL=%~1
set TERRAMIND_GGUF_MAX_TOKENS=1024
set TERRAMIND_TERRAFORM_PATH=C:\Users\shubh\Downloads\terramind\.build\tools\terraform-1.16.4\terraform.exe
set TERRAMIND_EVAL_COUNT=12
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind held-out eval (parse rate + provider validity)
echo   model: %~1
echo   log  : %~2
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Continue'; & 'C:\Users\shubh\Downloads\terramind\services\analyzer-api\.venv\Scripts\python.exe' -u 'C:\Users\shubh\Downloads\terramind\scripts\eval_provider.py' *>&1 | Tee-Object -FilePath '%~2'"
echo.
echo === eval finished (exit %ERRORLEVEL%) ===
pause
