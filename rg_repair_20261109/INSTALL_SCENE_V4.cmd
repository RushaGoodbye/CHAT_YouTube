@echo off
chcp 65001 >nul
setlocal
set "PY=F:\RG_AUTO_EDIT\RG Auto Edit Runtime\venv\Scripts\python.exe"
if not exist "%PY%" (echo RG Runtime missing. No files modified. & pause & exit /b 2)
"%PY%" -X utf8 "%~dp0install_v4.py" --package-dir "%~dp0candidate" --apply
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo INSTALL NOT COMPLETED. CHECK STUDIO CLOSED AND QUEUE IDLE.
pause
exit /b %RC%
