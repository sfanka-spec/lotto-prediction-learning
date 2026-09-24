@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run START_LOTTERY_AI.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade -r requirements.txt
pause
