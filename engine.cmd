@echo off
rem Runs the engine with its own Python environment. Usage: engine.cmd <command> [options]
setlocal
set "VENV=%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\reelengine\venv"
if not exist "%VENV%\Scripts\python.exe" set "VENV=%LOCALAPPDATA%\reelengine\venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo Python environment not found. Run setup.cmd first.
  exit /b 1
)
set "PATH=%VENV%\Scripts;%PATH%"
set "PYTHONUTF8=1"
cd /d "%~dp0"
"%VENV%\Scripts\python.exe" -m engine %*
