@echo off
setlocal EnableExtensions EnableDelayedExpansion

for %%I in ("%~dp0..\..") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%"

set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
set "REQ_FILE=daemon\requirements-windows.txt"
set "TRAY_SCRIPT=%REPO_ROOT%\daemon\tray_windows.py"
set "UV_CACHE_DIR=%REPO_ROOT%\.codex-tmp\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%REPO_ROOT%\.codex-tmp\uv-python"
set "UV_EXE="

set "CLAWDMETER_CONFIG_DIR=%USERPROFILE%\.config\clawdmeter"
set "GO_CRED_FILE=%CLAWDMETER_CONFIG_DIR%\opencode-go-credentials.json"
set "TRAY_CONFIG_DIR=%LOCALAPPDATA%\Clawdmeter"
set "TRAY_CONFIG=%TRAY_CONFIG_DIR%\config.json"

rem ── Check for --setup / -s flag ──────────────────────────────────────────
set "FORCE_SETUP="
for %%a in (%*) do (
    if /i "%%a"=="--setup" set "FORCE_SETUP=1"
    if /i "%%a"=="/setup" set "FORCE_SETUP=1"
    if /i "%%a"=="-s" set "FORCE_SETUP=1"
)

rem ── Provider setup wizard ───────────────────────────────────────────────

:setup_prompt
if defined FORCE_SETUP goto :show_setup_menu

rem Check if already configured
if exist "%TRAY_CONFIG%" (
    findstr /i "provider" "%TRAY_CONFIG%" >nul 2>nul
    if !errorlevel! equ 0 goto :check_go_cookie
)
if defined CLAWDMETER_PROVIDER goto :check_go_cookie

goto :show_setup_menu

:check_go_cookie
rem If provider is OpenCode Go and cred file exists, ask about refresh
set "CURRENT_PROVIDER=claude"
if defined CLAWDMETER_PROVIDER set "CURRENT_PROVIDER=%CLAWDMETER_PROVIDER%"
if exist "%TRAY_CONFIG%" (
    for /f "tokens=2 delims=:" %%p in ('findstr "provider" "%TRAY_CONFIG%"') do (
        set "CURRENT_PROVIDER=%%~p"
    )
)
set "CURRENT_PROVIDER=%CURRENT_PROVIDER:"=%
set "CURRENT_PROVIDER=%CURRENT_PROVIDER: =%

if /i "%CURRENT_PROVIDER%"=="go" (
    if exist "%GO_CRED_FILE%" (
        echo.
        echo OpenCode Go credentials found.
        echo Press R to refresh auth cookie, or any other key to continue...
        choice /c RN /n /t 5 /d N >nul 2>nul
        if !errorlevel! equ 1 goto :setup_opencode_go
    ) else (
        goto :setup_opencode_go
    )
)
goto :after_setup

:show_setup_menu
echo.
echo   ====== Clawdmeter Setup ======
echo.
echo   Select your AI provider:
echo.
echo     1) Claude (default — needs claude login)
echo     2) Codex (needs Codex auth)
echo     3) OpenCode Go (needs workspace ID + auth cookie)
echo.
echo     (already configured? just press Enter to skip, or
echo      run "%~nx0 --setup" to force this menu)
echo.
set /p "PROVIDER_CHOICE=Enter choice (1/2/3) [skip]: "
if "!PROVIDER_CHOICE!"=="" goto :after_setup

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
if not exist "%TRAY_CONFIG_DIR%" mkdir "%TRAY_CONFIG_DIR%" >nul 2>nul
echo {"provider": "%CLAWDMETER_PROVIDER%"} > "%TRAY_CONFIG%"
echo Saved provider to tray config.
goto :after_setup

:setup_opencode_go
cls
echo.
echo   ====== OpenCode Go Setup ======
echo.
echo   How to get your credentials:
echo.
echo     1) Go to https://opencode.ai and log in
echo     2) The URL will be: https://opencode.ai/workspace/wrk_.../go
echo        The "wrk_..." part is your Workspace ID
echo     3) Open DevTools (F12) ^> Application ^> Cookies ^>
echo        Copy the "auth" cookie value (starts with Fe26.2**)
echo.
if exist "%GO_CRED_FILE%" (
    echo   [Current credentials found — press Enter to keep or type new value]
    for /f "tokens=2 delims=:" %%w in ('findstr "workspace_id" "%GO_CRED_FILE%"') do (
        for /f "tokens=* delims= " %%a in ("%%~w") do set "OLD_WID=%%a"
    )
    set "OLD_WID=!OLD_WID:"=!
    set "OLD_WID=!OLD_WID:,=!"
)
echo.
set /p "GO_WID=Workspace ID (wrk_...^) [!OLD_WID!]: "
if "!GO_WID!"=="" set "GO_WID=!OLD_WID!"
if not defined GO_WID (
    echo Workspace ID is required.
    pause
    goto :setup_opencode_go
)

set /p "GO_COOKIE=Auth Cookie (Fe26.2**...^): "
if not defined GO_COOKIE (
    echo Auth cookie is required.
    pause
    goto :setup_opencode_go
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

rem Save provider to tray config
if not exist "%TRAY_CONFIG_DIR%" mkdir "%TRAY_CONFIG_DIR%" >nul 2>nul
echo {"provider": "go"} > "%TRAY_CONFIG%"

echo.
echo OpenCode Go credentials saved to %GO_CRED_FILE%
echo (permissions restricted to current user only)
echo.
echo Tip: when the cookie expires, just run "%~nx0 --setup"

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
    echo Check your internet connection, then run scripts\windows\Start Clawdmeter.cmd again.
    exit /b 1
)

call :find_uv
if errorlevel 1 (
    echo uv installed, but this window cannot find it yet.
    echo Close this window and double-click scripts\windows\Start Clawdmeter.cmd again.
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
    echo Delete the .venv folder and run scripts\windows\Start Clawdmeter.cmd again.
    exit /b 1
)
exit /b 0

:fail
echo.
echo Clawdmeter could not start. Check the message above, then press any key to close.
pause >nul
exit /b 1
