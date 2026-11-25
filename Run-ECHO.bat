@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 goto unavailable

if not exist ".venv\Scripts\python.exe" (
    echo ECHO's Python environment is missing. Run setup.bat first.
    goto failed
)

if /i "%~1"=="--build" (
    call :build_dashboard
    if errorlevel 1 goto failed
) else if not exist "frontend\dist\index.html" (
    call :build_dashboard
    if errorlevel 1 goto failed
)

pushd "backend"
if errorlevel 1 goto failed
"..\.venv\Scripts\python.exe" -m app launch
set "echo_exit=%errorlevel%"
popd
if not "%echo_exit%"=="0" goto failed
popd
exit /b 0

:build_dashboard
where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo Install Node.js to build the dashboard. See the Quick start in README.md.
    exit /b 1
)
pushd "frontend"
if errorlevel 1 exit /b 1
if not exist "node_modules\.bin\vite.cmd" (
    call npm.cmd ci
    if errorlevel 1 (
        popd
        exit /b 1
    )
)
call npm.cmd run build
set "echo_build_exit=%errorlevel%"
popd
exit /b %echo_build_exit%

:failed
popd
:unavailable
echo ECHO could not start. See the message above or check README.md.
pause
exit /b 1
