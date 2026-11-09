@echo off
chcp 65001 >nul
setlocal
set "PY=F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe"
if not exist "%PY%" (echo Missing RG runtime. & pause & exit /b 2)
"%PY%" -X utf8 "%~dp0install_v3.py" --rollback-latest
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
