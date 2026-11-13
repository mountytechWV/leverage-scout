@echo off
REM Leverage Scout: rebuild the ETF list on this computer.
REM Needs Python installed and a .env file with your API keys (copy .env.example to .env).
cd /d "%~dp0"
if not exist .env (
  echo No .env file found. Copy .env.example to .env and paste in your API keys.
  pause
  exit /b 1
)
python scripts\build_etfs.py
echo.
echo Finished. Open index.html to see the results.
pause
