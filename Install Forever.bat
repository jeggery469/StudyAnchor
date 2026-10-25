@echo off
REM ============================================================
REM  Install Focus "forever" mode:
REM    - background guard (SYSTEM) enforces the block every minute
REM    - the Focus app auto-launches (as the popout) at every login
REM  Double-click once and approve the admin prompt.
REM ============================================================
setlocal

net session >nul 2>&1
if %errorlevel% NEQ 0 (
    echo Requesting administrator permission...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

set "PYW="
for /f "delims=" %%i in ('where pyw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
    echo ERROR: Could not find pyw.exe / pythonw.exe on PATH. Install Python first.
    pause & exit /b 1
)
echo Using: %PYW%
echo Folder: %CD%
echo.

REM 1) guard: runs AS YOU (elevated) every minute. It enforces the block and relaunches the
REM    app if it was closed. It must run as you, not SYSTEM: SYSTEM can't start the
REM    Microsoft-Store Python, and a SYSTEM-launched app window would be invisible.
schtasks /Create /F /RU "%USERNAME%" /IT /RL HIGHEST /SC MINUTE /MO 1 ^
    /TN "FocusGuard" /TR "\"%PYW%\" \"%CD%\guard.py\""
if %errorlevel% NEQ 0 (
    echo.
    echo ERROR: could not create the FocusGuard task. Blocking will NOT be always-on.
    pause & exit /b 1
)

REM 2) app popout: interactive at every login
schtasks /Create /F /IT /RL HIGHEST /SC ONLOGON /DELAY 0000:15 ^
    /TN "FocusApp" /TR "\"%PYW%\" \"%CD%\focusapp.py\""

REM remove any task from the older version
schtasks /Delete /F /TN "FocusSession" 2>nul

REM enforce right now (this also opens the app if it isn't running)
"%PYW%" "%CD%\guard.py"

echo.
echo Installed tasks:
schtasks /Query /TN "FocusGuard" /FO LIST | findstr /B "TaskName Status"
schtasks /Query /TN "FocusApp"   /FO LIST | findstr /B "TaskName Status"
echo.
echo ============================================================
echo  Done. Blocking is enforced every minute during your scheduled
echo  hours, and StudyAnchor reopens itself within a minute if it's closed.
echo ============================================================
echo.
pause
