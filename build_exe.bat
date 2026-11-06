@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)
echo.
echo EXE: %~dp0dist\SAP2000JointAxes.exe
pause
