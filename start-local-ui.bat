@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Local Python environment not found: .venv\Scripts\python.exe
  echo Prepare the offline environment before disconnecting from the internet.
  pause
  exit /b 1
)

echo Starting Offline Story Studio on http://127.0.0.1:7860
".venv\Scripts\python.exe" -m comfyui_py_workflow.local_ui
echo.
echo Offline Story Studio stopped.
pause
