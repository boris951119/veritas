@echo off
cd /d "%~dp0"
set "PY="
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY if exist "%CD%\.runtime\python.exe" set "PY=%CD%\.runtime\python.exe"
if not defined PY (
  echo Run start.bat first.
  pause
  exit /b 1
)
echo Installing Docling from local wheels. Failure does not block the default demo.
"%PY%" "%CD%\scripts\offline_install.py" --docling
pause
