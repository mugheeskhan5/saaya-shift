@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="data" goto pipeline
if "%~1"=="evaluate" goto pipeline
if "%~1"=="verify" goto pipeline
echo Usage: make data ^| evaluate ^| verify
exit /b 2
:pipeline
if not exist "%~dp0.venv\Scripts\python.exe" goto missing
"%~dp0.venv\Scripts\python.exe" -m saayashift.cli %*
exit /b %errorlevel%
:missing
echo Create .venv and install requirements-pipeline.txt first. See README.md.
exit /b 1
