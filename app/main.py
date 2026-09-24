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

from pydantic import BaseModel

from . import notes, taste
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
    user, avisos = None, []
    if sp and sp.authenticated:
        try:
            me = sp.me()
            user = {"name": me.get("display_name"), "id": me.get("id")}
        except SpotifyAuthError:
            pass
        except Exception as e:  # noqa: BLE001 — p. ej. Spotify limitando peticiones
            avisos.append(f"Spotify no responde ahora mismo: {e}")
    return {
        "spotify_configured": bool(CLIENT_ID),
        "spotify_user": user,
        "lastfm_enabled": lf is not None,
        "statsfm_enabled": sf is not None,
        "warnings": (avisos + (sf.privacy_warnings() if sf else [])
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
    """El mismo perfil que ve la IA por MCP, para echarle un ojo.

    Sale de stats.fm, no de Spotify: así no gasta cuota (ver app/taste.py).
    """
    if not sf:
        raise HTTPException(400, "stats.fm no está configurado (STATSFM_USERNAME)")
    return taste.taste_profile(sf)


# ---------- feedback rápido ----------

class Opinion(BaseModel):
    artista: str
    album: str = ""
    veredicto: str
    nota: str = ""


@app.get("/semana")
def semana():
    return FileResponse(STATIC / "semana.html")


@app.get("/api/pendientes")
def pendientes():
    """Discos por escuchar o por valorar, agrupados por la lista en la que
    entraron. La nota "En la lista «X»" la pone create_playlist."""
    grupos: dict[str, list] = {}
    for a in notes.cargar()["albumes"].values():
        if a.get("veredicto") != "pendiente":
            continue
        nota = a.get("nota") or ""
        lista = nota.split("«", 1)[1].split("»", 1)[0] if "«" in nota else "Otros pendientes"
        grupos.setdefault(lista, []).append({"artista": a["artista"], "album": a["album"],
                                             "desde": a.get("desde")})
    return {"veredictos": [v for v in notes.VEREDICTOS if v not in ("pendiente", "escuchado")],
            "listas": [{"lista": k, "albumes": v} for k, v in grupos.items()]}


@app.post("/api/opinion")
def opinar(o: Opinion):
    try:
        entrada = notes.anotar("album" if o.album else "artista", o.artista,
                               o.veredicto, o.nota, o.album)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "guardado": entrada}
