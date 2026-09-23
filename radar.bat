@echo off
REM Pasa el radar de novedades y emergentes (sin Spotify). Tarda un par de minutos.
cd /d "%~dp0"
if not exist .venv (echo Ejecuta primero setup.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -u scripts\radar.py
echo.
pause
