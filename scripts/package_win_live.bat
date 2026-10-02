@echo off
title TerraMind - Package win32-x64 (live progress)
cd /d "C:\Users\shubh\Downloads\terramind"
echo ============================================================
echo   Packaging TerraMind for Windows x64 (vscode-win32-x64-min)
echo   Log: C:\Users\shubh\Downloads\terramind\package-log.txt
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "npm run gulp vscode-win32-x64-min *>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\package-log.txt'"

echo.
echo === Packaging finished (exit %ERRORLEVEL%) ===
echo Output should be under .build\win32-x64
pause
