@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 gui.py
) else (
  python gui.py
)
if errorlevel 1 (
  echo.
  echo Pythonの起動に失敗しました。Python 3.11以降とTkinterを確認してください。
  pause
)
