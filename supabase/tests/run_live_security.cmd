@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" supabase\tests\launch_live_security.py
) else (
    py -3.14 supabase\tests\launch_live_security.py
)
set "TEST_RESULT=%ERRORLEVEL%"
echo.
echo Report: work\supabase-live-report.json
echo Exit code: %TEST_RESULT%  (0=PASS, 1=FAIL, 2=NOT RUN or BLOCKED)
pause
exit /b %TEST_RESULT%
