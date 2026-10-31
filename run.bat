@echo off
cd /d "%~dp0"
python src\main.py
if errorlevel 1 pause
