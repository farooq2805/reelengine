@echo off
rem One-time setup on a new laptop: Python environment, FFmpeg, Ollama and the vision model.
setlocal
set "VENV=%LOCALAPPDATA%\reelengine\venv"
if not exist "%VENV%\Scripts\python.exe" python -m venv "%VENV%"
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
where ffmpeg >nul 2>nul || winget install --id Gyan.FFmpeg -e
where ollama >nul 2>nul || winget install --id Ollama.Ollama -e
ollama pull qwen3-vl:2b-instruct
echo.
echo Setup done. Next: engine.cmd login YOUR_SPARE_ACCOUNT
