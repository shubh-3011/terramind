@echo off
title TerraMind - Provider validity evaluation (live progress)
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TERRAMIND_GENERATION_ENGINE=gguf
set TERRAMIND_GGUF_MODEL=C:\Users\shubh\Downloads\terramind\.build\terramind-gguf\terramind-qwen2.5-coder-1.5b-terraform-merged-Q4_K_M.gguf
set TERRAMIND_GGUF_MAX_TOKENS=1024
set TERRAMIND_TERRAFORM_PATH=C:\Users\shubh\Downloads\terramind\.build\tools\terraform-1.16.4\terraform.exe
set TERRAMIND_EVAL_COUNT=12
set PYTHONPATH=C:\Users\shubh\Downloads\terramind\services\analyzer-api
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
echo ============================================================
echo   TerraMind - held-out eval: parse rate + provider validity
echo   Live progress below. A copy is saved to:
echo     C:\Users\shubh\Downloads\terramind\.build\provider-eval-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& 'C:\Users\shubh\Downloads\terramind\services\analyzer-api\.venv\Scripts\python.exe' -u 'C:\Users\shubh\Downloads\terramind\scripts\eval_provider.py' 2>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\.build\provider-eval-log.txt'"

echo.
echo === Evaluation finished (exit %ERRORLEVEL%) ===
pause
