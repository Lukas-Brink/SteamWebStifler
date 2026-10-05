@echo off
title Building SteamWebStifler.exe
cd /d "%~dp0"

echo =========================================================
echo   Compiling SteamWebStifler into Standalone .EXE
echo =========================================================

python -m PyInstaller --clean SteamWebStifler.spec

if exist "dist\SteamWebStifler.exe" (
    echo.
    echo Copying binary to project root...
    copy /y "dist\SteamWebStifler.exe" "SteamWebStifler.exe" >nul
    echo.
    echo =========================================================
    echo   BUILD SUCCESSFUL!
    echo   Executable ready at: SteamWebStifler.exe
    echo =========================================================
) else (
    echo.
    echo [ERROR] Build failed. Check the output above.
)

pause
