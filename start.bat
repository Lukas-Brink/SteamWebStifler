@echo off
title SteamWebStifler
cd /d "%~dp0"

if exist "SteamWebStifler.exe" (
    start "" "SteamWebStifler.exe"
) else (
    python main.py
)
if errorlevel 1 pause
