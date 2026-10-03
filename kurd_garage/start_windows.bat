@echo off
title Kurd Garage
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py
if not exist .venv\Scripts\python.exe (
    echo First time setup, please wait...
    %PY% -m venv .venv || goto error
)
.venv\Scripts\python -c "import flask, qrbill, waitress" 2>nul || (
    echo Installing, please wait...
    .venv\Scripts\python -m pip install -r requirements.txt || goto error
)
.venv\Scripts\python app.py
:error
echo.
echo If you see an error above, take a photo of this window and send it.
pause
