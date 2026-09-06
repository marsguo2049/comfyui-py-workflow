@echo off
setlocal
cd /d "%~dp0"

set "CPW_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%CPW_PYTHON%" goto missing_python
if /I "%~1"=="--diagnose" goto diagnose

echo Starting Offline Studio - Batch Tools on http://127.0.0.1:7860/#batch
"%CPW_PYTHON%" -m comfyui_py_workflow.local_ui --view batch
set "CPW_EXIT_CODE=%ERRORLEVEL%"

if not "%CPW_EXIT_CODE%"=="0" (
  echo.
  echo The UI stopped with exit code %CPW_EXIT_CODE%.
  echo If Studio is already running, open http://127.0.0.1:7860/#batch
  pause
)
exit /b %CPW_EXIT_CODE%

:diagnose
"%CPW_PYTHON%" -c "import sys; import comfyui_py_workflow.local_ui, comfyui_py_workflow.batch_studio; print('Python:', sys.executable); print('Offline Studio batch tools: OK')"
exit /b %ERRORLEVEL%

:missing_python
echo Local Python environment was not found:
echo %CPW_PYTHON%
echo Create it with: python -m venv .venv
echo Then install with: .venv\Scripts\python.exe -m pip install -e .
pause
exit /b 1
