@echo off
REM Runs the whole Focus test suite (about 2 minutes). Add --fast to skip the window tests.
REM It never touches your real hosts file or settings.
cd /d "%~dp0"
set "PY="
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY for /f "delims=" %%i in ('where py 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
    echo Could not find Python. Install it from python.org first.
    pause & exit /b 1
)
"%PY%" run_tests.py %*
echo.
pause
