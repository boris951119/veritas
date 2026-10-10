@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%CD%"
set "LOG=%ROOT%\launch-log.txt"
set "WHEELS=%ROOT%\vendor\wheels\win_amd64"
set "FAIL="
echo ===== %DATE% %TIME% =====>> "%LOG%"
echo root=%ROOT%>> "%LOG%"
echo.
echo veritas launcher
echo log: %LOG%
echo.

set "PY="
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >> "%LOG%" 2>&1
  if not errorlevel 1 set "PY=%ROOT%\.venv\Scripts\python.exe"
)

if not defined PY (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >> "%LOG%" 2>&1
  if not errorlevel 1 (
    echo [1] creating venv with Python 3.12
    echo creating venv>> "%LOG%"
    py -3 -m venv "%ROOT%\.venv" >> "%LOG%" 2>&1
    if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
  )
)

if defined PY goto havepy

if exist "%ROOT%\.runtime\python.exe" goto haveruntime

echo [1] extracting portable Python, no network
echo extract embed>> "%LOG%"
if not exist "%ROOT%\vendor\python\python-3.12.10-embed-amd64.zip" set "FAIL=missing portable Python zip. Unzip the full offline bundle, do not run from inside the zip."
if defined FAIL goto fail
mkdir "%ROOT%\.runtime" 2>nul
powershell -NoProfile -Command "Expand-Archive -Force -LiteralPath '%ROOT%\vendor\python\python-3.12.10-embed-amd64.zip' -DestinationPath '%ROOT%\.runtime'" >> "%LOG%" 2>&1
if errorlevel 1 set "FAIL=could not unzip portable Python"
if defined FAIL goto fail
copy /Y "%ROOT%\vendor\python\python312._pth" "%ROOT%\.runtime\python312._pth" >> "%LOG%" 2>&1
echo bootstrapping pip>> "%LOG%"
"%ROOT%\.runtime\python.exe" "%ROOT%\vendor\python\get-pip.py" --no-index --find-links "%WHEELS%" >> "%LOG%" 2>&1
if errorlevel 1 set "FAIL=pip bootstrap failed"
if defined FAIL goto fail

:haveruntime
if not defined PY set "PY=%ROOT%\.runtime\python.exe"

:havepy
echo using !PY!>> "%LOG%"
echo [2] offline install
if not exist "%WHEELS%\." set "FAIL=missing %WHEELS%"
if defined FAIL goto fail
"!PY!" "%ROOT%\scripts\offline_install.py" >> "%LOG%" 2>&1
if errorlevel 1 set "FAIL=offline install failed"
if defined FAIL goto fail
echo [3] start server, then open the browser
set "VERITAS_PY=!PY!"
"!PY!" "%ROOT%\scripts\win_embed.py" prepare >> "%LOG%" 2>&1
if errorlevel 1 set "FAIL=could not prepare server launcher"
if defined FAIL goto fail
start "veritas-server" run-server.bat
echo waiting for http://127.0.0.1:8765/ >> "%LOG%"
"!PY!" "%ROOT%\scripts\win_embed.py" wait >> "%LOG%" 2>&1
if errorlevel 1 set "FAIL=server did not stay up. Read the veritas-server window."
if defined FAIL goto fail
start "" "http://127.0.0.1:8765/"
echo browser opened>> "%LOG%"
echo.
echo Workbench is running in the other window. Do not close that window.
goto end

:fail
echo.
echo ERROR: !FAIL!
echo ERROR: !FAIL!>> "%LOG%"
echo ----- last lines of launch-log.txt -----
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 30"

:end
echo.
pause
endlocal
