@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
set "REQ_FILE=daemon\requirements-windows.txt"
set "TRAY_SCRIPT=%CD%\daemon\tray_windows.py"
set "UV_CACHE_DIR=%CD%\.codex-tmp\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%CD%\.codex-tmp\uv-python"
set "UV_EXE="

call :ensure_python
if errorlevel 1 goto fail

echo Installing or checking Clawdmeter dependencies...
"%PYTHON_EXE%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo Installing pip into the Clawdmeter environment...
    "%PYTHON_EXE%" -m ensurepip --upgrade
    if errorlevel 1 goto fail
)
"%PYTHON_EXE%" -m pip install --quiet -r "%REQ_FILE%"
if errorlevel 1 goto fail

echo Enabling Start at login...
"%PYTHON_EXE%" -c "import os, sys; sys.path.insert(0, os.getcwd()); import daemon.autostart_windows as a; a.enable(tray_script=os.path.abspath(r'daemon\tray_windows.py'))"
if errorlevel 1 goto fail

echo Starting Clawdmeter tray...
"%PYTHON_EXE%" -c "import os, sys, subprocess; pythonw = os.path.join(sys.base_exec_prefix, 'pythonw.exe'); script = os.path.abspath(r'daemon\tray_windows.py'); subprocess.Popen([pythonw, script], cwd=os.getcwd())"
if errorlevel 1 goto fail
exit /b 0

:find_uv
set "UV_EXE="
for /f "delims=" %%U in ('where uv 2^>nul') do (
    if not defined UV_EXE set "UV_EXE=%%U"
)
if defined UV_EXE exit /b 0
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    exit /b 0
)
exit /b 1

:ensure_uv
call :find_uv
if not errorlevel 1 exit /b 0

echo Installing the small Python helper uv...
echo First run may need internet access and may take a minute.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { irm https://astral.sh/uv/install.ps1 | iex } catch { exit 1 }"
if errorlevel 1 (
    echo Could not install uv automatically.
    echo Check your internet connection, then run Start Clawdmeter.cmd again.
    exit /b 1
)

call :find_uv
if errorlevel 1 (
    echo uv installed, but this window cannot find it yet.
    echo Close this window and double-click Start Clawdmeter.cmd again.
    exit /b 1
)
exit /b 0

:ensure_python
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "import sys" >nul 2>nul
    if not errorlevel 1 exit /b 0
    echo Existing .venv is broken; recreating it...
    rmdir /s /q ".venv" >nul 2>nul
)

call :ensure_uv
if errorlevel 1 exit /b 1

echo Installing/checking Python 3.11...
if not exist ".codex-tmp" mkdir ".codex-tmp" >nul 2>nul
"%UV_EXE%" python install 3.11
if errorlevel 1 exit /b 1

echo Creating Clawdmeter Python environment...
"%UV_EXE%" venv --python 3.11 ".venv"
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo Python environment was created but did not start correctly.
    echo Delete the .venv folder and run Start Clawdmeter.cmd again.
    exit /b 1
)
exit /b 0

:fail
echo.
echo Clawdmeter could not start. Check the message above, then press any key to close.
pause >nul
exit /b 1
