@echo off
title TerraMind - Analyzer API (http://127.0.0.1:8000)
cd /d "C:\Users\shubh\Downloads\terramind\services\analyzer-api"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TERRAMIND_GGUF_N_GPU_LAYERS=-1
set TERRAMIND_GGUF_N_CTX=8192
set TERRAMIND_GGUF_MAX_TOKENS=4096
set TERRAMIND_GGUF_TEMPERATURE=0.1
echo ============================================================
echo   TerraMind Analyzer API on http://127.0.0.1:8000
echo   Bundled model auto-discovered from models\*.gguf (no Ollama)
echo   Leave this window OPEN while you use TerraMind.
echo ============================================================
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
