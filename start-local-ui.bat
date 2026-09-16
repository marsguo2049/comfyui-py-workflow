@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Local Python environment not found: .venv\Scripts\python.exe
  echo Prepare the offline environment before disconnecting from the internet.
  pause
  exit /b 1
)

echo Starting ComfyUI Workbench on http://127.0.0.1:7860/#batch
".venv\Scripts\python.exe" scripts\launch.py %*
set "CPW_EXIT_CODE=%ERRORLEVEL%"
if not "%CPW_EXIT_CODE%"=="0" pause
exit /b %CPW_EXIT_CODE%
