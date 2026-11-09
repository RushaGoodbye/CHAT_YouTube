@echo off
chcp 65001 >nul
setlocal
set "PY=C:\Users\fauto\AppData\Local\Programs\RG Auto Edit Runtime\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe"
if not exist "%PY%" (echo Python runtime missing. No files changed. & pause & exit /b 2)
"%PY%" -X utf8 "%~dp0install_v2.py" --package-dir "%~dp0candidate" --apply
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo UPDATE NOT INSTALLED. CHECK STUDIO IS CLOSED AND QUEUE IDLE.
pause
exit /b %RC%
