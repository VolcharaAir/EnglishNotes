@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Install development dependencies as described in README.md.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m englishnotes
