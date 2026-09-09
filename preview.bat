@echo off
REM Muestra los 5 albumes de hoy sin crear nada (doble clic). Requiere haber ejecutado setup.bat y hecho login.
cd /d "%~dp0"
if not exist .venv (echo Ejecuta primero setup.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m app.weekly preview > preview_salida.txt 2>&1
type preview_salida.txt
echo.
echo (La salida se ha guardado en preview_salida.txt)
pause
