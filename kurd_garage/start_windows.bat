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
rem Create / update the desktop icon ("Kurd Garage" or "Kurd Garage + phone")
set SC_NAME=Kurd Garage
set SC_FILE=start_windows.bat
if "%HOST%"=="0.0.0.0" set SC_NAME=Kurd Garage + phone
if "%HOST%"=="0.0.0.0" set SC_FILE=start_phone.bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\%SC_NAME%.lnk');$s.TargetPath='%~dp0%SC_FILE%';$s.WorkingDirectory='%~dp0';$s.IconLocation='%SystemRoot%\System32\shell32.dll,12';$s.Save()" >nul 2>nul
.venv\Scripts\python app.py
:error
echo.
echo If you see an error above, take a photo of this window and send it.
pause
