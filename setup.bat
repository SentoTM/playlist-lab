@echo off
REM Puesta en marcha de Playlist Lab en Windows (doble clic).
REM Crea el entorno virtual, instala dependencias, arranca la web y abre el navegador.
cd /d "%~dp0"

python --version 2>nul || (echo No se encuentra Python. Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH". & pause & exit /b 1)

if not exist .env (echo Falta el fichero .env. Copia .env.example a .env y rellenalo. & pause & exit /b 1)

if not exist .venv (
  echo Creando entorno virtual...
  python -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
echo Instalando dependencias...
pip install -q -r requirements.txt || (pause & exit /b 1)

echo.
echo Arrancando la web en http://127.0.0.1:8888 ...
echo Pulsa "Iniciar sesion con Spotify" en el navegador y autoriza (solo la primera vez).
echo Deja esta ventana abierta mientras uses la app. Ctrl+C para parar.
echo.
start "" http://127.0.0.1:8888
uvicorn app.main:app --port 8888
pause
