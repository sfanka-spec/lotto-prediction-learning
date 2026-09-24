@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo   Lottery AI V1.6.5 - Windows Launcher
echo ==============================================

where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py
) else (
  set PY=python
)

if not exist ".venv\Scripts\python.exe" (
  echo [First run] Creating local Python environment...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  if errorlevel 1 goto :fail
) else (
  call .venv\Scripts\activate.bat
)

python app.py
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Startup failed. Please copy the error message and send it to ChatGPT.
pause
exit /b 1
