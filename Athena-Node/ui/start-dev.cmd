@echo off
setlocal

set "LAUNCHER=%~dp0scripts\start-dev.ps1"

if /I "%~1"=="--self-test" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" -SelfTest
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" %*
)

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Startup failed. Review the error above.
    pause
)

exit /b %EXIT_CODE%
