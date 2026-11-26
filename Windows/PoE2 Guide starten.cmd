@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title PoE2 Ingame Guide v.0.23.0

rem Release: app\ next to this starter. Working copy: Produktiv\Windows\ next to Produktiv\app\.
set "POE2_APP=%~dp0app"
if not exist "%POE2_APP%\poe2_standalone_overlay.py" set "POE2_APP=%~dp0..\app"
if not exist "%POE2_APP%\poe2_standalone_overlay.py" (
    echo Erst im Explorer auf "Alle extrahieren" klicken.
    echo Dann "PoE2 Guide starten" aus dem entpackten Ordner oeffnen.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0companion-python.ps1" -AppDirectory "%POE2_APP%"
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
