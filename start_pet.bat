@echo off
cd /d "%~dp0"
if not "%~1"=="" (
    py -3 pet.py %*
    exit /b %ERRORLEVEL%
)
where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pyw -3 pet.py
    exit /b 0
)
start "" pythonw pet.py
