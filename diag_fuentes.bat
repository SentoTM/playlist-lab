@echo off
REM Diagnostico de las fuentes gratuitas (no gasta cuota de Spotify).
cd /d "%~dp0"
if not exist .venv (echo Ejecuta primero setup.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
python scripts\diag_fuentes.py > diag_fuentes.txt 2>&1
type diag_fuentes.txt
echo.
pause
