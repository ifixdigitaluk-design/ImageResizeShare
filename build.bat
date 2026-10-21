@echo off
REM ==========================================================================
REM  Image Resize & Share - one-click Windows build
REM  Needs: Python 3.11+ from python.org (tick "Add python.exe to PATH")
REM  Result: dist\ImageResizeShare\ImageResizeShare.exe
REM ==========================================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Download it from https://www.python.org/downloads/
  pause & exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat

echo Installing libraries...
python -m pip install --upgrade pip >nul
pip install -r requirements-dev.txt || (pause & exit /b 1)

if not exist vendor\realesrgan\realesrgan-ncnn-vulkan.exe (
  echo Downloading the AI upscaling engine ^(Real-ESRGAN, ~45 MB^)...
  if not exist vendor mkdir vendor
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference='SilentlyContinue';" ^
    "Invoke-WebRequest -Uri 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip' -OutFile 'vendor\realesrgan.zip';" ^
    "Expand-Archive -Path 'vendor\realesrgan.zip' -DestinationPath 'vendor\realesrgan' -Force;" ^
    "Remove-Item 'vendor\realesrgan.zip';" ^
    "Get-ChildItem 'vendor\realesrgan' -Include *.jpg,*.png,*.mp4 -Recurse | Remove-Item"
  if not exist vendor\realesrgan\realesrgan-ncnn-vulkan.exe (
    echo WARNING: AI engine download failed - the app will still work using Enhanced upscaling.
  )
)

echo Running tests...
python -m pytest -q tests || (echo Unit tests failed & pause & exit /b 1)
python main.py --selftest || (echo Self-test failed & pause & exit /b 1)

echo Building the app...
pyinstaller --noconfirm ImageResizeShare.spec || (pause & exit /b 1)

echo Checking the built app...
dist\ImageResizeShare\ImageResizeShare.exe --selftest
if errorlevel 1 (echo Built app self-test failed & pause & exit /b 1)

echo.
echo ==========================================================
echo  Done!  Your app is in:  dist\ImageResizeShare\
echo  Double-click ImageResizeShare.exe to start it.
echo  (Optional) Build an installer: open installer.iss in Inno Setup and press Compile.
echo ==========================================================
pause
