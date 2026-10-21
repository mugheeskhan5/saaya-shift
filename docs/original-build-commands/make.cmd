@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="data" goto pipeline
if "%~1"=="evaluate" goto pipeline
if "%~1"=="verify" goto pipeline
if "%~1"=="test" goto tests
if "%~1"=="dashboard" goto dashboard
echo Usage: make data ^| evaluate ^| verify ^| test ^| dashboard
exit /b 2
:pipeline
"%~dp0.venv\Scripts\python.exe" -m saayashift.cli %~1
exit /b %errorlevel%
:tests
"%~dp0.venv\Scripts\python.exe" -m pytest -q
exit /b %errorlevel%
:dashboard
"%~dp0.venv\Scripts\python.exe" -m streamlit run app.py
exit /b %errorlevel%
