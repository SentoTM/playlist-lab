"""Servidor MCP de Playlist Lab.

Expone las funciones de la app como herramientas MCP para usarlas
conversacionalmente desde Claude (Desktop/Cowork) o, en modo HTTP + túnel,
desde ChatGPT.

    python mcp_server.py            # stdio (Claude Desktop)
    python mcp_server.py --http     # streamable HTTP en http://127.0.0.1:8877/mcp
"""
import datetime as dt
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).resolve().parent / ".env")

from app.clients.lastfm import LastfmClient          # noqa: E402
from app.clients.spotify import SpotifyClient        # noqa: E402
from app.clients.statsfm import StatsfmClient        # noqa: E402
from app.engines import lastfm_engine, profile as profile_engine, statsfm_engine  # noqa: E402
from app.engines.core import blend                   # noqa: E402
from app.resolve import resolve_on_spotify           # noqa: E402
from app.weekly import build_day, build_week         # noqa: E402

PORT = os.getenv("PORT", "8888")
mcp = FastMCP("playlist-lab", host="127.0.0.1", port=8877)


def _clients() -> tuple[SpotifyClient, LastfmClient | None, StatsfmClient | None]:
    sp = SpotifyClient(os.getenv("SPOTIFY_CLIENT_ID", ""),
                       f"http://127.0.0.1:{PORT}/callback")
    lf = (LastfmClient(os.getenv("LASTFM_API_KEY", ""),
                       os.getenv("LASTFM_USERNAME") or None)
          if os.getenv("LASTFM_API_KEY") else None)
    sf = (StatsfmClient(os.getenv("STATSFM_USERNAME", ""))
          if os.getenv("STATSFM_USERNAME") else None)
    return sp, lf, sf


def _require_auth(sp: SpotifyClient):
    if not sp.authenticated:
        raise RuntimeError(
            "Sin sesión de Spotify. Arranca la web app "
            f"(uvicorn app.main:app --port {PORT}), abre http://127.0.0.1:{PORT} "
            "y haz login una vez; el token se guarda y el MCP lo reutiliza.")


@mcp.tool()
def status() -> dict:
    """Estado de la configuración: qué fuentes están activas y si hay sesión de Spotify."""
    sp, lf, sf = _clients()
    user = None
    if sp.authenticated:
        try:
            me = sp.me()
            user = me.get("display_name") or me.get("id")
        except Exception as e:
            user = f"error: {e}"
    return {
        "spotify_configured": bool(os.getenv("SPOTIFY_CLIENT_ID")),
        "spotify_session": user,
        "lastfm": bool(lf), "statsfm": bool(sf),
        "warnings": sf.privacy_warnings() if sf else [],
    }


@mcp.tool()
def preview_day_albums(date: str = "", variant: int = 0) -> dict:
    """Previsualiza los 5 álbumes del día SIN crear la playlist.

    Categorías: moderno similar (últimos 5 años, artista desconocido),
    clásico similar (pre-2000), género adyacente, sorpresa de género lejano,
    e imprescindible. `date` en formato YYYY-MM-DD (hoy si se omite);
    `variant` cambia la tirada manteniendo el mismo día.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    d = dt.date.fromisoformat(date) if date else dt.date.today()
    return build_day(sp, lf, sf, d, variant, create=False)


@mcp.tool()
def create_day_playlist(date: str = "", variant: int = 0) -> dict:
    """Genera y CREA en Spotify la playlist de 5 álbumes de un día.

    Mismos parámetros que preview_day_albums. Devuelve la URL de la playlist creada.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    d = dt.date.fromisoformat(date) if date else dt.date.today()
    return build_day(sp, lf, sf, d, variant, create=True)


@mcp.tool()
def generate_week(start: str = "", variant: int = 0, dry_run: bool = False) -> dict:
    """Genera las 5 playlists de álbumes de lunes a viernes de una semana.

    `start`: lunes de inicio (YYYY-MM-DD); por defecto, el próximo lunes
    (u hoy si es lunes). `dry_run=True` solo previsualiza sin crear nada.
    Evita repetir álbumes dentro de la semana. Puede tardar un par de minutos.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    s = dt.date.fromisoformat(start) if start else None
    return build_week(sp, lf, sf, s, variant, create=not dry_run)


@mcp.tool()
def custom_playlist(name: str = "", size: int = 30, novelty: float = 0.5,
                    profile_weight: float = 1.0, lastfm_weight: float = 0.8,
                    statsfm_weight: float = 0.6, per_artist_max: int = 2,
                    exclude_known: bool = False, create: bool = False) -> dict:
    """Playlist de canciones a medida mezclando los motores de recomendación.

    Motores: perfil de Spotify (tus tops y la órbita de tus artistas),
    similares de Last.fm y redescubrimiento del historial de stats.fm.
    `novelty` 0..1 (0 = tus clásicos, 1 = descubrimiento).
    Con create=False devuelve la lista para revisarla; con create=True la
    publica en Spotify con el nombre dado.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)

    known = profile_engine.known_track_keys(sp)
    pools = {}
    warnings = []
    if profile_weight > 0:
        pools["profile"] = (profile_weight, profile_engine.generate(sp, novelty))
    if lastfm_weight > 0 and lf:
        pools["lastfm"] = (lastfm_weight, lastfm_engine.generate(lf, sp))
    elif lastfm_weight > 0:
        warnings.append("Last.fm no configurado")
    if statsfm_weight > 0 and sf:
        cands = statsfm_engine.generate(sf, sp, known, 1.0 - novelty * 0.5)
        if cands:
            pools["statsfm"] = (statsfm_weight, cands)
        else:
            warnings.append("stats.fm sin datos")
    elif statsfm_weight > 0:
        warnings.append("stats.fm no configurado")

    mixed = blend(pools, size, known if exclude_known else set(), per_artist_max)
    resolved = resolve_on_spotify(sp, mixed)[:size]

    out = {
        "tracks": [{"name": c.name, "artist": c.artist, "uri": c.spotify_uri,
                    "source": c.source, "reason": c.reason} for c in resolved],
        "warnings": warnings, "created": None,
    }
    if create and resolved:
        uris = [c.spotify_uri for c in resolved if c.spotify_uri]
        pl = sp.create_playlist(name or "Playlist Lab (custom)",
                                "Generada con Playlist Lab vía MCP", uris)
        out["created"] = {"id": pl["id"],
                         "url": pl.get("external_urls", {}).get("spotify")}
    return out


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
