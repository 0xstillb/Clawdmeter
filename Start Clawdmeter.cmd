@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
set "REQ_FILE=daemon\requirements-windows.txt"
set "TRAY_SCRIPT=%CD%\daemon\tray_windows.py"
set "UV_CACHE_DIR=%CD%\.codex-tmp\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%CD%\.codex-tmp\uv-python"
set "UV_EXE="

rem ── Provider setup wizard ───────────────────────────────────────────────
set "CLAWDMETER_CONFIG_DIR=%USERPROFILE%\.config\clawdmeter"
set "GO_CRED_FILE=%CLAWDMETER_CONFIG_DIR%\opencode-go-credentials.json"

rem Check if provider is already configured (tray config or env)
set "HAS_PROVIDER="
if exist "%LOCALAPPDATA%\Clawdmeter\config.json" (
    findstr /i "provider" "%LOCALAPPDATA%\Clawdmeter\config.json" >nul && set "HAS_PROVIDER=1"
)
if defined CLAWDMETER_PROVIDER set "HAS_PROVIDER=1"
if exist "%GO_CRED_FILE%" set "HAS_PROVIDER=1"

if not defined HAS_PROVIDER (
    echo.
    echo   ====== Clawdmeter Setup ======
    echo.
    echo   Select your AI provider:
    echo.
    echo     1) Claude (default — needs claude login)
    echo     2) Codex (needs Codex auth)
    echo     3) OpenCode Go (needs workspace ID + auth cookie)
    echo.
    set /p "PROVIDER_CHOICE=Enter choice (1/2/3) [1]: "
    if "!PROVIDER_CHOICE!"=="" set PROVIDER_CHOICE=1

    if "!PROVIDER_CHOICE!"=="3" (
        goto :setup_opencode_go
    ) else if "!PROVIDER_CHOICE!"=="2" (
        set "CLAWDMETER_PROVIDER=codex"
        echo Setting provider to Codex...
    ) else (
        set "CLAWDMETER_PROVIDER=claude"
        echo Setting provider to Claude...
    )

    rem Save provider to tray config
    if not exist "%LOCALAPPDATA%\Clawdmeter\" mkdir "%LOCALAPPDATA%\Clawdmeter" >nul 2>nul
    echo {"provider": "%CLAWDMETER_PROVIDER%"} > "%LOCALAPPDATA%\Clawdmeter\config.json"
    echo Saved provider to tray config.
    goto :after_setup

    :setup_opencode_go
    echo.
    echo   -- OpenCode Go Setup --
    echo.
    echo   How to get your credentials:
    echo     1) Go to https://opencode.ai and log in
    echo     2) Open your workspace: the URL will be
    echo        https://opencode.ai/workspace/wrk_.../go
    echo     3) The "wrk_..." part is your Workspace ID
    echo     4) Press F12 ^> Application ^> Cookies ^> copy "auth" value
    echo.
    set /p "GO_WID=Enter your Workspace ID (wrk_...): "
    set /p "GO_COOKIE=Enter your Auth Cookie (Fe26.2**...): "

    if not defined GO_WID (
        echo Workspace ID is required. Aborting.
        exit /b 1
    )
    if not defined GO_COOKIE (
        echo Auth cookie is required. Aborting.
        exit /b 1
    )

    if not exist "%CLAWDMETER_CONFIG_DIR%" mkdir "%CLAWDMETER_CONFIG_DIR%" >nul 2>nul

    rem Write credentials file
    > "%GO_CRED_FILE%" (
        echo {
        echo   "workspace_id": "%GO_WID%",
        echo   "auth_cookie": "%GO_COOKIE%"
        echo }
    )
    icacls "%GO_CRED_FILE%" /inheritance:r /grant "%USERNAME%:(R,W)" >nul 2>nul

    rem Also save provider to tray config
    if not exist "%LOCALAPPDATA%\Clawdmeter\" mkdir "%LOCALAPPDATA%\Clawdmeter" >nul 2>nul
    echo {"provider": "go"} > "%LOCALAPPDATA%\Clawdmeter\config.json"

    echo.
    echo OpenCode Go credentials saved to %GO_CRED_FILE%
    echo (permissions restricted to current user only)
    goto :after_setup
)

:after_setup
echo.

rem ── Normal startup ──────────────────────────────────────────────────────

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