@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM Pick a healthy Python 3.11–3.13 via the py launcher.
REM Prefer newer versions, but skip incomplete installs (missing Lib/).
set "PY_CMD="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY_CMD (
    py -%%V -c "import sys; from pathlib import Path; raise SystemExit(0 if (Path(sys.base_prefix)/'Lib').is_dir() else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -%%V"
  )
)

if not defined PY_CMD (
  echo No healthy Python 3.11-3.13 found.
  echo.
  echo Your C:\Python313 install may be incomplete ^(missing Lib/^).
  echo Install a full Python with Chocolatey ^(admin terminal^):
  echo   choco install python311 -y
  echo Then open a new terminal and run setup.bat again.
  exit /b 1
)

echo Using: %PY_CMD%
%PY_CMD% scripts\setup_env.py %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Setup failed. If pip/numpy errors persist, try:
  echo   setup.bat --force
  exit /b %ERR%
)
exit /b 0
