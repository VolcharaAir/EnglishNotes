@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" supabase\tests\diagnose_connection.py
) else (
    py -3.14 supabase\tests\diagnose_connection.py
)
set "CHECK_RESULT=%ERRORLEVEL%"
echo.
echo Read-only connection check exit code: %CHECK_RESULT%
pause
exit /b %CHECK_RESULT%
