@echo off
setlocal
if /I not "%~d0"=="D:" (
    echo Extract the EnglishNotes project to D:\EnglishNotes first.
    pause
    exit /b 1
)
set "TEMP=D:\EnglishNotesData\temp"
set "TMP=D:\EnglishNotesData\temp"
set "PIP_CACHE_DIR=D:\EnglishNotesData\pip-cache"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%TEMP%" exit /b 1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Create a Python 3.14 virtual environment on D: as described in README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -B -m englishnotes
if errorlevel 1 pause
