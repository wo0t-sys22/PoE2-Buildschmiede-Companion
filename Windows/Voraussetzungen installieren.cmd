@echo off
setlocal DisableDelayedExpansion
title PoE2 Companion - Voraussetzungen
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0companion-python.ps1" -Install
set "result=%errorlevel%"
echo.
pause
exit /b %result%
