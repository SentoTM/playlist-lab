@echo off
REM Sube tus datos al servidor de Railway (o: subir_datos.bat --bajar para una copia)
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python scripts\subir_datos.py %*
pause
