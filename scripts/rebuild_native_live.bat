@echo off
title TerraMind - Rebuild native modules (live progress)
cd /d "C:\Users\shubh\Downloads\terramind"
echo ============================================================
echo   Rebuilding VS Code native modules (per-module progress)
echo   Log: C:\Users\shubh\Downloads\terramind\rebuild-native.log
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\shubh\Downloads\terramind\scripts\rebuild_native.ps1" *>&1 | Tee-Object -FilePath "C:\Users\shubh\Downloads\terramind\rebuild-native.log"

echo.
echo === Native rebuild finished ===
pause
