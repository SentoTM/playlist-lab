"""Playlist Lab — web mínima: login de Spotify, estado y vistazo al perfil.

La generación de playlists se hace conversando (servidor MCP, ver README).
Esta web sirve para autenticarse una vez y comprobar que todo funciona.
"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from . import taste
from .clients.lastfm import LastfmClient
from .clients.spotify import SpotifyAuthError, SpotifyClient
from .clients.statsfm import StatsfmClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PORT = int(os.getenv("PORT", "8888"))
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
STATIC = Path(__file__).resolve().parents[1] / "static"

app = FastAPI(title="Playlist Lab")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("playlist_lab")

sp = SpotifyClient(CLIENT_ID, REDIRECT_URI) if CLIENT_ID else None
lf = (LastfmClient(os.getenv("LASTFM_API_KEY", ""), os.getenv("LASTFM_USERNAME") or None)
      if os.getenv("LASTFM_API_KEY") else None)
sf = (StatsfmClient(os.getenv("STATSFM_USERNAME", ""))
      if os.getenv("STATSFM_USERNAME") else None)


@app.exception_handler(Exception)
async def _unhandled(request, exc: Exception):
    """Que la UI muestre el error real en vez de 'Internal Server Error'."""
    log.exception("Error no controlado en %s", request.url.path)
    if isinstance(exc, SpotifyAuthError):
        return JSONResponse({"detail": f"Sesión de Spotify inválida: {exc}"}, status_code=401)
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/login")
def login():
    if not sp:
        raise HTTPException(500, "Falta SPOTIFY_CLIENT_ID en .env")
    return RedirectResponse(sp.auth_url())


@app.get("/callback")
def callback(code: str = "", error: str = ""):
    if error or not code:
        raise HTTPException(400, f"Login cancelado o fallido: {error}")
    sp.exchange_code(code)
    return RedirectResponse("/")


@app.post("/api/logout")
def logout():
    if sp:
        sp.logout()
    return {"ok": True}


@app.get("/api/status")
def status():
    user = None
    if sp and sp.authenticated:
        try:
            me = sp.me()
            user = {"name": me.get("display_name"), "id": me.get("id")}
        except SpotifyAuthError:
            pass
    return {
        "spotify_configured": bool(CLIENT_ID),
        "spotify_user": user,
        "lastfm_enabled": lf is not None,
        "statsfm_enabled": sf is not None,
        "warnings": ((sf.privacy_warnings() if sf else [])
                     + (["Faltan permisos nuevos de Spotify ("
                         + ", ".join(sp.missing_scopes())
                         + "): pulsa 'salir' y vuelve a iniciar sesión."]
                        if sp and sp.authenticated and sp.missing_scopes() else [])),
        "mcp_config": mcp_config(),
    }


def mcp_config() -> dict:
    """Bloque listo para pegar en claude_desktop_config.json."""
    root = Path(__file__).resolve().parents[1]
    py = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return {"mcpServers": {"playlist-lab": {
        "command": str(py), "args": [str(root / "mcp_server.py")]}}}


@app.get("/api/profile")
def profile():
    """El mismo perfil que ve la IA por MCP, para echarle un ojo."""
    if not sp or not sp.authenticated:
        raise HTTPException(401, "Inicia sesión con Spotify primero")
    return taste.taste_profile(sp, lf, sf)
