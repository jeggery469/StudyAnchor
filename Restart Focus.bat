@echo off
REM Stops any running Focus app (even the elevated login one) and relaunches the
REM latest code from this folder. Use this after updating the files.
setlocal

net session >nul 2>&1
if %errorlevel% NEQ 0 (
    echo Requesting administrator permission...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo Stopping any running StudyAnchor app...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'focusapp\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

set "PYW="
for /f "delims=" %%i in ('where pyw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW set "PYW=pythonw"

echo Starting the latest version...
start "" "%PYW%" "%CD%\focusapp.py"

echo.
echo Done - StudyAnchor restarted with the latest code.
timeout /t 2 >nul
