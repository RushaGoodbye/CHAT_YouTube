@echo off
chcp 65001 >nul
setlocal
set "PY=F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe"
if not exist "%PY%" (echo Missing RG runtime. No files changed. & pause & exit /b 2)
"%PY%" -X utf8 "%~dp0install_v3.py" --package-dir "%~dp0candidate" --apply
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo UPDATE BLOCKED OR FAILED. STUDIO MUST BE CLOSED.
pause
exit /b %RC%
