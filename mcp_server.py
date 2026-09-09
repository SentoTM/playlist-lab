"""Servidor MCP de Playlist Lab: centro de consulta y creación.

La app no recomienda: da datos (qué escuchas, qué conoces, señales de
Last.fm, búsqueda en Spotify) y ejecuta (resuelve y crea playlists). La
curación la hace la IA que conversa contigo (Claude o ChatGPT), combinando
tu perfil con su conocimiento de escenas, discografías y crítica.

    python mcp_server.py            # stdio (Claude Desktop)
    python mcp_server.py --http     # streamable HTTP en http://127.0.0.1:8877/mcp (ChatGPT vía túnel)
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).resolve().parent / ".env")

from app import library, taste                       # noqa: E402
from app.clients.lastfm import LastfmClient          # noqa: E402
from app.clients.spotify import SpotifyClient        # noqa: E402
from app.clients.statsfm import StatsfmClient        # noqa: E402
from app.text import norm                            # noqa: E402

PORT = os.getenv("PORT", "8888")
mcp = FastMCP("playlist-lab", host="127.0.0.1", port=8877)

_cache: dict = {}
CACHE_TTL = 1800  # 30 min: los tops no cambian en una conversación


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
            "Sin sesión de Spotify. Ejecuta setup.bat (o uvicorn app.main:app "
            f"--port {PORT}), abre http://127.0.0.1:{PORT} y haz login una vez; "
            "el token se guarda y el MCP lo reutiliza.")


def _cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


# ---------- consulta ----------

@mcp.tool()
def status() -> dict:
    """Estado: fuentes configuradas, sesión de Spotify y avisos."""
    sp, lf, sf = _clients()
    user = None
    if sp.authenticated:
        try:
            me = sp.me()
            user = me.get("display_name") or me.get("id")
        except Exception as e:  # noqa: BLE001
            user = f"error: {e}"
    return {
        "spotify_configured": bool(os.getenv("SPOTIFY_CLIENT_ID")),
        "spotify_session": user,
        "lastfm": bool(lf), "statsfm": bool(sf),
        "warnings": sf.privacy_warnings() if sf else [],
    }


@mcp.tool()
def taste_profile() -> dict:
    """Perfil de gustos del usuario: EMPIEZA SIEMPRE POR AQUÍ antes de proponer.

    Devuelve, por periodo (4 semanas / 6 meses / años), sus artistas top con
    géneros y sus canciones top en Spotify; sus tops recientes en Last.fm
    (incluye escuchas fuera de Spotify); su top histórico completo (stats.fm);
    `fase_actual` (artistas nuevos en el corto plazo que no están en el
    largo) y `generos_principales` agregados. Se cachea 30 min.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    return _cached("profile", lambda: taste.taste_profile(sp, lf, sf))


@mcp.tool()
def listening_history(source: str = "statsfm", kind: str = "artists",
                      range: str = "lifetime", limit: int = 50, offset: int = 0) -> list:
    """Historial en bruto cuando el perfil no basta.

    source: "statsfm" (historial completo; range: weeks|months|lifetime),
    "lastfm" (range: 7day|1month|3month|6month|12month|overall) o
    "spotify" (range: short_term|medium_term|long_term). kind: artists|tracks.
    `offset` permite paginar (p. ej. artistas del 50 al 100).
    """
    sp, lf, sf = _clients()
    if source == "statsfm":
        if not sf:
            raise RuntimeError("stats.fm no configurado")
        items = (sf.top_artists(range, limit + offset) if kind == "artists"
                 else sf.top_tracks(range, limit + offset))
        return items[offset:]
    if source == "lastfm":
        if not (lf and lf.username):
            raise RuntimeError("Last.fm no configurado")
        items = (lf.user_top_artists(range, limit + offset) if kind == "artists"
                 else lf.user_top_tracks(range, limit + offset))
        return items[offset:]
    _require_auth(sp)
    if kind == "artists":
        return [{"name": a["name"], "genres": a.get("genres", [])}
                for a in sp.top_artists(range, min(limit + offset, 50))][offset:]
    return [{"name": t.get("name"),
             "artist": (t.get("artists") or [{}])[0].get("name"),
             "album": (t.get("album") or {}).get("name")}
            for t in sp.top_tracks(range, min(limit + offset, 50))][offset:]


@mcp.tool()
def check_known(artists: list[str], deep: bool = True) -> dict:
    """¿Conoce ya el usuario a estos artistas? Úsalo para filtrar propuestas.

    Devuelve por artista: known (bool) y evidencia (puesto en tops de
    Spotify, scrobbles en Last.fm, streams en stats.fm). Con deep=True
    consulta además en Last.fm los que no aparecen en ningún top (detecta
    artistas escuchados poco pero escuchados).
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    known = _cached("known", lambda: taste.known_artists(sp, lf, sf))
    out = {}
    for name in artists:
        e = known.get(norm(name))
        if e:
            out[name] = {"known": True, **{k: v for k, v in e.items() if k != "artist"}}
        elif deep and lf and lf.username:
            plays = lf.user_artist_playcount(name)
            out[name] = {"known": plays > 3, "lastfm_plays": plays}
        else:
            out[name] = {"known": False}
    return out


@mcp.tool()
def similar_artists(artist: str, limit: int = 15, only_unknown: bool = True) -> list:
    """Artistas similares según Last.fm (señal colaborativa, no crítica).

    Con only_unknown=True se descartan los que el usuario ya conoce.
    Contrasta el resultado con tu propio criterio: Last.fm tiende a lo obvio.
    """
    sp, lf, sf = _clients()
    if not lf:
        raise RuntimeError("Last.fm no configurado")
    sims = lf.similar_artists(artist, limit * 2 if only_unknown else limit)
    if only_unknown:
        _require_auth(sp)
        known = _cached("known", lambda: taste.known_artists(sp, lf, sf))
        sims = [s for s in sims if norm(s["name"]) not in known]
    return sims[:limit]


@mcp.tool()
def search(query: str, kind: str = "album", limit: int = 5) -> list:
    """Busca en Spotify. kind: album | track | artist. Acepta filtros de
    Spotify: 'album:Nombre artist:Grupo', 'year:2020-2024', 'genre:post-punk'."""
    sp, _, _ = _clients()
    _require_auth(sp)
    if kind == "album":
        return [{"album": a.get("name"),
                 "artist": (a.get("artists") or [{}])[0].get("name"),
                 "year": (a.get("release_date") or "")[:4],
                 "type": a.get("album_type"), "n_tracks": a.get("total_tracks"),
                 "id": a.get("id")} for a in sp.search_album(query, limit)]
    if kind == "artist":
        return [{"artist": a.get("name"), "genres": a.get("genres", []),
                 "popularity": a.get("popularity"), "id": a.get("id")}
                for a in sp.search_artist(query, limit)]
    return [library._track_summary(t) for t in sp.search_track(query, limit)]


@mcp.tool()
def album_info(artist: str, album: str) -> dict:
    """Detalle de un álbum (año, duración, pistas) para decidir si encaja
    (p. ej. máx. ~70 min para una playlist de álbumes)."""
    sp, _, _ = _clients()
    _require_auth(sp)
    a = library.find_album(sp, artist, album)
    if not a:
        return {"error": f"No encuentro '{album}' de {artist} en Spotify"}
    return library.album_details(sp, a["id"])


# ---------- creación ----------

@mcp.tool()
def resolve(tracks: list[str] = [], albums: list[str] = []) -> dict:
    """Comprueba en Spotify una propuesta SIN crear nada.

    tracks: lista de "Artista – Canción"; albums: lista de "Artista – Álbum"
    (se añaden completos). Devuelve lo resuelto (con año y duración), lo no
    encontrado y los minutos totales. Úsalo antes de create_playlist para
    corregir títulos o sustituir lo que falte.
    """
    sp, _, _ = _clients()
    _require_auth(sp)
    res = library.resolve_items(sp, tracks, albums)
    res.pop("uris", None)
    return res


@mcp.tool()
def create_playlist(name: str, tracks: list[str] = [], albums: list[str] = [],
                    description: str = "Curada con Playlist Lab",
                    public: bool = False) -> dict:
    """Crea la playlist en Spotify a partir de "Artista – Canción" y/o
    "Artista – Álbum" (álbumes completos, en el orden dado, tras las canciones).

    Devuelve la URL y lo que no se pudo resolver (se omite, no bloquea).
    Pide confirmación al usuario antes de llamar a esto.
    """
    sp, _, _ = _clients()
    _require_auth(sp)
    res = library.resolve_items(sp, tracks, albums)
    if not res["uris"]:
        return {"error": "Nada que añadir: no se resolvió ningún elemento",
                "unresolved": res["unresolved"]}
    created = library.create_playlist(sp, name, description, res["uris"], public)
    return {"created": created, "total_minutes": res["total_minutes"],
            "resolved": [r["input"] for r in res["resolved"]],
            "unresolved": res["unresolved"]}


# ---------- guía de curación ----------

@mcp.prompt()
def curar_playlist(encargo: str = "") -> str:
    """Cómo curar una playlist para este usuario con las herramientas."""
    return f"""Eres el curador musical de este usuario. Encargo: {encargo or '(pregunta qué le apetece)'}

Método:
1. Llama a taste_profile y lee con calma: fase actual, géneros principales, qué escucha ahora vs. históricamente.
2. Piensa como un crítico que conoce escenas, sellos, discografías y reseñas (no como un algoritmo de similitud): busca artistas y discos que encajen con su gusto pero que probablemente no conozca, o que amplíen en una dirección coherente. Mezcla épocas y evita los nombres obvios salvo que el encargo lo pida.
3. Pasa tus candidatos por check_known y descarta los conocidos (o justifica incluirlos). similar_artists de Last.fm es solo una señal más.
4. Verifica con resolve que todo existe en Spotify (y con album_info duraciones si es una playlist de álbumes: ~70 min máximo por disco).
5. Presenta la propuesta con una frase por elección (por qué encaja y qué aporta) y pide confirmación.
6. Solo entonces create_playlist. Nombre corto y descriptivo."""


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
