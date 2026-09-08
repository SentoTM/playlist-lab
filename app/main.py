"""Playlist Lab — generador local de playlists de Spotify con varios motores."""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from .clients.lastfm import LastfmClient
from .clients.spotify import SpotifyAuthError, SpotifyClient
from .clients.statsfm import StatsfmClient
from .engines import lastfm_engine, profile, statsfm_engine
from .engines.core import Candidate, blend
from .resolve import resolve_on_spotify

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PORT = int(os.getenv("PORT", "8888"))
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"

app = FastAPI(title="Playlist Lab")
STATIC = Path(__file__).resolve().parents[1] / "static"

sp = SpotifyClient(CLIENT_ID, REDIRECT_URI) if CLIENT_ID else None
lf = (LastfmClient(os.getenv("LASTFM_API_KEY", ""), os.getenv("LASTFM_USERNAME") or None)
      if os.getenv("LASTFM_API_KEY") else None)
sf = (StatsfmClient(os.getenv("STATSFM_USERNAME", ""))
      if os.getenv("STATSFM_USERNAME") else None)


# ---------- páginas / auth ----------

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
        "warnings": sf.privacy_warnings() if sf else [],
    }


# ---------- generación ----------

class PreviewRequest(BaseModel):
    engines: dict[str, float]      # {"profile": 1.0, "lastfm": 0.8, "statsfm": 0.5}
    size: int = 30
    novelty: float = 0.5           # 0 = lo de siempre, 1 = descubrimiento
    per_artist_max: int = 2
    exclude_known: bool = False    # excluir canciones ya en tus tops/recientes

class CreateRequest(BaseModel):
    name: str
    description: str = "Generada con Playlist Lab"
    uris: list[str]
    public: bool = False


@app.post("/api/preview")
def preview(req: PreviewRequest):
    if not sp or not sp.authenticated:
        raise HTTPException(401, "Inicia sesión con Spotify primero")

    known = profile.known_track_keys(sp)
    pools: dict[str, tuple[float, list[Candidate]]] = {}
    errors: list[str] = []

    if req.engines.get("profile", 0) > 0:
        pools["profile"] = (req.engines["profile"],
                            profile.generate(sp, novelty=req.novelty))

    if req.engines.get("lastfm", 0) > 0:
        if not lf:
            errors.append("Last.fm no está configurado (LASTFM_API_KEY en .env)")
        else:
            pools["lastfm"] = (req.engines["lastfm"],
                               lastfm_engine.generate(lf, sp))

    if req.engines.get("statsfm", 0) > 0:
        if not sf:
            errors.append("stats.fm no está configurado (STATSFM_USERNAME en .env)")
        else:
            cands = statsfm_engine.generate(
                sf, sp, recent_keys=known,
                rediscover_weight=1.0 - req.novelty * 0.5)
            if not cands:
                errors.append("stats.fm no devolvió datos (¿perfil privado o API caída?)")
            else:
                pools["statsfm"] = (req.engines["statsfm"], cands)

    if not pools:
        raise HTTPException(400, "Ningún motor disponible. " + "; ".join(errors))

    exclude = known if req.exclude_known else set()
    mixed = blend(pools, size=req.size, exclude_keys=exclude,
                  per_artist_max=req.per_artist_max)
    resolved = resolve_on_spotify(sp, mixed)[: req.size]

    return {
        "tracks": [{
            "name": c.name, "artist": c.artist, "uri": c.spotify_uri,
            "id": c.spotify_id, "score": round(c.score, 3),
            "source": c.source, "reason": c.reason, "image": c.album_image,
        } for c in resolved],
        "warnings": errors,
    }


@app.post("/api/create")
def create(req: CreateRequest):
    if not sp or not sp.authenticated:
        raise HTTPException(401, "Inicia sesión con Spotify primero")
    if not req.uris:
        raise HTTPException(400, "La lista está vacía")
    playlist = sp.create_playlist(req.name, req.description, req.uris,
                                  public=req.public)
    return {
        "id": playlist["id"],
        "url": playlist.get("external_urls", {}).get("spotify"),
        "name": playlist["name"],
    }
