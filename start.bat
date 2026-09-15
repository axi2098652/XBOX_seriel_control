@echo off
setlocal
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Project Python environment was not found.
    echo Please follow the installation instructions in README.md.
    pause
    exit /b 1
)
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
exit /b %errorlevel%
