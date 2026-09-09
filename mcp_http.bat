@echo off
REM Sirve el MCP por HTTP en http://127.0.0.1:8877/mcp (para ChatGPT via tunel).
REM En otra ventana: cloudflared tunnel --url http://127.0.0.1:8877  (o ngrok http 8877)
cd /d "%~dp0"
if not exist .venv (echo Ejecuta primero setup.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
python mcp_server.py --http
pause
