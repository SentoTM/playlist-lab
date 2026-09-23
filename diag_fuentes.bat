@echo off
REM Diagnostico de las fuentes gratuitas (no gasta cuota de Spotify).
REM Tarda un par de minutos: mientras veas lineas nuevas, esta trabajando.
cd /d "%~dp0"
if not exist .venv (echo Ejecuta primero setup.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -u scripts\diag_fuentes.py
echo.
pause
