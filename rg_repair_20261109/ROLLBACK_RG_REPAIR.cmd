@echo off
chcp 65001 >nul
setlocal
set "PY=C:\Users\fauto\AppData\Local\Programs\RG Auto Edit Runtime\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Python runtime not found.
  pause
  exit /b 2
)
"%PY%" -X utf8 "%~dp0install.py" --rollback-latest
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
