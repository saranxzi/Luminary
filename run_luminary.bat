@echo off
setlocal
if exist "%~dp0main.py" (
    set "APPDIR=%~dp0"
) else (
    set "APPDIR=%~dp0app"
)
set "VENV=%APPDIR%\.venv"
set "PY311=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

if not exist "%VENV%\Scripts\pythonw.exe" (
    echo Setting up Luminary for the first time...
    if not exist "%PY311%" (
        echo Python 3.11 64-bit was not found at "%PY311%".
        echo Install it from python.org and run this again.
        pause
        exit /b 1
    )
    "%PY311%" -m venv "%VENV%" || (pause & exit /b 1)
    "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "%APPDIR%\requirements.txt" || (pause & exit /b 1)
    powershell -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%\tools\install_shortcut.ps1" >nul 2>&1
)

start "" "%VENV%\Scripts\pythonw.exe" "%APPDIR%\main.py"
