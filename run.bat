@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo Virtualenv missing. Running setup.bat ...
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)

"%VENV_PY%" -c "import numpy, cv2, PySide6" >nul 2>&1
if errorlevel 1 (
  echo Environment looks broken. Repairing with setup.bat ...
  call "%~dp0setup.bat" --force
  if errorlevel 1 exit /b 1
)

"%VENV_PY%" "%~dp0app.py" %*
exit /b %ERRORLEVEL%
