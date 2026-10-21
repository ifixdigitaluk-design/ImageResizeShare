@echo off
REM Run the app from source (after build.bat has created .venv once)
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
  start "" .venv\Scripts\pythonw.exe main.py %*
) else (
  echo Run build.bat first to install the libraries.
  pause
)
