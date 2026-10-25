@echo off
REM Installs the modern UI toolkit (customtkinter). Optional - the app also
REM tries to install it automatically on first launch.
cd /d "%~dp0"
set "PY="
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY for /f "delims=" %%i in ('where py 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
    echo Could not find Python on PATH. Install it from python.org first.
    pause & exit /b 1
)
echo Installing customtkinter...
"%PY%" -m pip install --user customtkinter
echo.
echo Done. Launch with "Start Focus.bat".
pause
