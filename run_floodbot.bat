@echo off
title +FloodBot by cyber2 - Launcher
color 0a

echo ===================================================
echo           +FloodBot by cyber2 - LAUNCHER           
echo ===================================================
echo.

rem Check if venv folder exists. If not, jump to setup.
if not exist .venv goto SETUP
goto LAUNCH

:SETUP
echo [INFO] Virtual environment (.venv) not found.
echo [INFO] Setting up the system for the first time...
echo.

python -m venv .venv
if %errorlevel% neq 0 goto PYERROR

echo.
echo [INFO] Installing required libraries from requirements.txt...
call .venv\Scripts\pip install -r requirements.txt
if %errorlevel% neq 0 goto PIPERROR

echo.
echo [SUCCESS] Setup completed successfully!
echo.

:LAUNCH
echo [INFO] Checking binary dependencies (ffmpeg, yt-dlp)...
call .venv\Scripts\python download_binaries.py

echo [INFO] Launching browser to http://127.0.0.1:8080...
start http://127.0.0.1:8080

echo [INFO] Starting +FloodBot engine...
echo.
call .venv\Scripts\python app.py
goto END

:PYERROR
echo [ERROR] Python is not installed or not added to PATH.
echo Please install Python and check "Add Python to PATH" box.
pause
exit /b

:PIPERROR
echo [ERROR] Dependency installation failed.
pause
exit /b

:END
pause
