"""Playlist Lab — generador local de playlists de Spotify con varios motores."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .clients.lastfm import LastfmClient
from .clients.spotify import SpotifyAuthError, SpotifyClient
from .clients.statsfm import StatsfmClient
from .engines import lastfm_engine, profile, statsfm_engine
from .engines.core import Candidate, blend, track_key
from .resolve import resolve_on_spotify

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

PORT = int(os.getenv("PORT", "8888"))
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"

app = FastAPI(title="Playlist Lab")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("playlist_lab")


@app.exception_handler(Exception)
async def _unhandled(request, exc: Exception):
    """Que la UI muestre el error real en vez de 'Internal Server Error'."""
    log.exception("Error no controlado en %s", request.url.path)
    if isinstance(exc, SpotifyAuthError):
        return JSONResponse({"detail": f"Sesión de Spotify inválida: {exc}"}, status_code=401)
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)
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
    if req.exclude_known:
        # "nuevas para mí" de verdad: también tu historial completo y Last.fm
        if sf:
            known |= statsfm_engine.lifetime_keys(sf, 500)
        if lf and lf.username:
            try:
                known |= {track_key(t["artist"], t["name"])
                          for t in lf.user_top_tracks("overall", 200)}
            except Exception:  # noqa: BLE001
                log.warning("No se pudo leer el top de Last.fm para excluir")
    pools: dict[str, tuple[float, list[Candidate]]] = {}
    errors: list[str] = []

    def run(engine: str, fn):
        """Ejecuta un motor aislado: si falla, aviso y seguimos con el resto."""
        try:
            cands = fn()
        except Exception as e:  # noqa: BLE001
            log.exception("Motor %s falló", engine)
            errors.append(f"Motor {engine} falló: {type(e).__name__}: {e}")
            return
        if cands:
            pools[engine] = (req.engines[engine], cands)
        else:
            errors.append(f"El motor {engine} no devolvió candidatos")

    if req.engines.get("profile", 0) > 0:
        run("profile", lambda: profile.generate(sp, novelty=req.novelty))

    if req.engines.get("lastfm", 0) > 0:
        if not lf:
            errors.append("Last.fm no está configurado (LASTFM_API_KEY en .env)")
        else:
            run("lastfm", lambda: lastfm_engine.generate(lf, sp))

    if req.engines.get("statsfm", 0) > 0:
        if not sf:
            errors.append("stats.fm no está configurado (STATSFM_USERNAME en .env)")
        else:
            run("statsfm", lambda: statsfm_engine.generate(
                sf, sp, recent_keys=known,
                rediscover_weight=1.0 - req.novelty * 0.5,
                only_new=req.exclude_known))

    if not pools:
        raise HTTPException(400, "Ningún motor disponible. " + "; ".join(errors))

    exclude = known if req.exclude_known else set()
    mixed = blend(pools, size=req.size, exclude_keys=exclude,
                  per_artist_max=req.per_artist_max)
    resolved = resolve_on_spotify(sp, mixed)[: req.size]

    stats = {e: {"candidatos": len(c), "elegidas": 0} for e, (_, c) in pools.items()}
    for c in resolved:
        stats[c.source.split("+")[0]]["elegidas"] += 1

    return {
        "stats": stats,
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
