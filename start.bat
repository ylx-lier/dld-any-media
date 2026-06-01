@echo off
chcp 65001 >nul
title DLD Any Media
echo.
echo   ***  DLD Any Media  ***
echo   Starting server at http://127.0.0.1:5128/
echo.
cd /d "%~dp0"
python app.py
pause
