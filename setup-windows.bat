@echo off
REM veritas one-shot env setup for Windows (pure ASCII output to avoid codepage issues)
setlocal
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

%PY% --version >nul 2>nul
if not %errorlevel%==0 (
    echo [ERROR] Python 3.10+ not found. Install from python.org ^(check "Add to PATH"^) or: winget install Python.Python.3.12
    exit /b 1
)
echo [1/4] Python found:
%PY% --version

if not exist .venv (
    echo [2/4] Creating venv ...
    %PY% -m venv .venv
) else (
    echo [2/4] venv already exists, reusing.
)

echo [3/4] Installing dependencies ...
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -r requirements.txt litellm
if not %errorlevel%==0 (
    echo [WARN] pip failed, retrying with Tsinghua mirror ...
    .venv\Scripts\python -m pip install -r requirements.txt litellm -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [4/4] Running tests (no API key needed) ...
.venv\Scripts\python -m pytest tests -q

echo.
echo Done. Offline demo : .venv\Scripts\python scripts\demo_offline.py
echo Online research    : copy .env.example to .env, fill keys, then .venv\Scripts\python -m app.pipeline cases\demo-solid-state
endlocal
