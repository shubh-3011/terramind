@echo off
title TerraMind - Web workbench (browser)
cd /d "C:\Users\shubh\Downloads\terramind"
echo ============================================================
echo   TerraMind web workbench (opens in your browser)
echo   Log: C:\Users\shubh\Downloads\terramind\web-log.txt
echo   Leave this window OPEN while you use the browser tab.
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "& 'C:\Users\shubh\Downloads\terramind\scripts\code-web.bat' *>&1 | Tee-Object -FilePath 'C:\Users\shubh\Downloads\terramind\web-log.txt'"
pause
