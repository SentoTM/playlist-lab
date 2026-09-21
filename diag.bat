@echo off
REM Diagnostico de los endpoints de Spotify (doble clic). Guarda la salida en diag_spotify.txt
cd /d "%~dp0"
if not exist .venv (echo Ejecuta primero setup.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
python scripts\diag_spotify.py > diag_spotify.txt 2>&1
type diag_spotify.txt
echo.
pause
