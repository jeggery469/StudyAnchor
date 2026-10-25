@echo off
REM Double-click to open the Focus app (the popout). No install needed.
cd /d "%~dp0"
set "PYW="
for /f "delims=" %%i in ('where pyw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW set "PYW=pythonw"
start "" "%PYW%" "%CD%\focusapp.py"
