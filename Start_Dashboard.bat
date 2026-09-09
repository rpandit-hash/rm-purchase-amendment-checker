@echo off
REM ============================================================
REM  RM Purchase Amendment Checker - Launcher
REM  Double-click this file to start the dashboard.
REM  First run will take a minute or two (one-time setup).
REM  After that, it starts in a few seconds.
REM ============================================================

setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   RM Purchase Amendment Checker
echo ============================================
echo.

REM ---- Find a working Python launcher ----
set "PYEXE="
set "PYARGS="

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYEXE=py"
    set "PYARGS=-3"
)

if not defined PYEXE (
    where python >nul 2>nul
    if %errorlevel%==0 set "PYEXE=python"
)

REM Fallback: Python installed but not added to PATH - check common locations.
if not defined PYEXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
    )
)

if not defined PYEXE (
    for /d %%D in ("C:\Program Files\Python3*") do (
        if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
    )
)

if not defined PYEXE (
    for /d %%D in ("C:\Python3*") do (
        if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
    )
)

if not defined PYEXE (
    echo [ERROR] Python was not found on this computer.
    echo Please install Python from https://www.python.org/downloads/
    echo ^(during install, tick "Add Python to PATH"^), then double-click this file again.
    pause
    exit /b 1
)

echo Using Python: %PYEXE% %PYARGS%

REM ---- Create the virtual environment on first run ----
if not exist "venv\Scripts\python.exe" (
    echo First-time setup: creating environment, please wait...
    "%PYEXE%" %PYARGS% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

REM ---- Install/update required packages ----
echo Checking required packages ^(only downloads if missing^)...
"venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Could not install required packages. Check your internet connection.
    pause
    exit /b 1
)

REM ---- Launch the dashboard ----
echo.
echo Starting dashboard... your browser will open automatically.
echo ^(To stop the app later, just close this window.^)
echo.
"venv\Scripts\python.exe" -m streamlit run frontend\amendment.py

pause
