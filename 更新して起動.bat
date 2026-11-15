@echo off
chcp 65001 >nul
echo P0-4安全対策: 未検証mainの自動更新は停止しています。インストール済み版を起動します。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync.ps1" -Launch
if errorlevel 1 pause
