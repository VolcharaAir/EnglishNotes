@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist ".venv\Scripts\python.exe" (
    echo Install the development environment from docs/cloud-desktop.md first.
    pause
    exit /b 2
)
".venv\Scripts\python.exe" supabase\tests\live_desktop.py --run
set "TEST_RESULT=%ERRORLEVEL%"
echo.
echo Exit code: %TEST_RESULT%  (0=PASS, 1=FAIL, 2=NOT RUN or BLOCKED)
pause
exit /b %TEST_RESULT%
