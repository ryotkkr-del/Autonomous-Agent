@echo off
chcp 65001 >nul
echo 警告: mainの開発版更新は検証済みReleaseではありません。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync.ps1" -DevMain -Launch
if errorlevel 1 pause
