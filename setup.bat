@echo off
setlocal DisableDelayedExpansion
set "echo_setup=%~dp0scripts\setup_echo.py"

if exist "%~dp0.venv\Scripts\python.exe" goto existing
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 goto python312
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto launcher
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto system_python
echo Install Python 3.11 or newer, then run setup.bat again. Python 3.12 is recommended.
goto failed

:existing
"%~dp0.venv\Scripts\python.exe" "%echo_setup%" %*
goto result

:python312
py -3.12 "%echo_setup%" %*
goto result

:launcher
py -3 "%echo_setup%" %*
goto result

:system_python
python "%echo_setup%" %*

:result
set "echo_exit=%errorlevel%"
if "%echo_exit%"=="0" exit /b 0
if "%echo_exit%"=="130" exit /b 130

:failed
if not defined echo_exit set "echo_exit=1"
echo ECHO setup stopped. See the message above or the Quick start in README.md.
if not defined CI pause
exit /b %echo_exit%
