@echo off
REM Highlight Recovery — local launcher
REM Starts uvicorn on http://127.0.0.1:8765 and opens the browser.
setlocal
cd /d "%~dp0"

REM Pick the python launcher when available, else fall back to "python".
where py >nul 2>&1
if %errorlevel%==0 (
    set PY=py -3
) else (
    set PY=python
)

echo Installing / verifying dependencies...
%PY% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo Dependency install failed. See error above.
    pause
    exit /b 1
)

echo.
echo Launching app at http://127.0.0.1:8123
echo Press Ctrl+C to stop the server.
echo.
start "" http://127.0.0.1:8123/
%PY% -m uvicorn backend.main:app --host 127.0.0.1 --port 8123
