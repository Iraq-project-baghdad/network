@echo off
title Baghdad Chat Live Neon
cd /d "%~dp0"
echo =====================================================
echo   Baghdad Chat Live Neon - Local Server
echo =====================================================
echo.
set PYTHON_CMD=
where py >nul 2>nul && set PYTHON_CMD=py -3
if not defined PYTHON_CMD where python >nul 2>nul && set PYTHON_CMD=python
if not defined PYTHON_CMD where python3 >nul 2>nul && set PYTHON_CMD=python3
if not defined PYTHON_CMD (
  echo Python is not installed. Install Python 3.10+ then run again.
  pause
  exit /b 1
)
echo Open this address in browser:
echo http://localhost:3000
echo.
%PYTHON_CMD% server.py
pause
