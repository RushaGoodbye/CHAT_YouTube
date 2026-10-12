@echo off
chcp 65001 > nul
echo RG Media Deck - ZIP Update
echo Close RG Media Deck and OBS capture before updating.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Apply_RG_Media_Deck_Update.ps1"
if errorlevel 1 pause
