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

from app import discovery, explore, library, taste   # noqa: E402
from app.clients.lastfm import LastfmClient          # noqa: E402
from app.clients.musicbrainz import MusicbrainzClient  # noqa: E402
from app.clients.press import FEEDS, PressClient     # noqa: E402
from app.clients.spotify import SpotifyClient        # noqa: E402
from app.clients.statsfm import StatsfmClient        # noqa: E402
from app.clients.wikipedia import WikipediaClient    # noqa: E402
from app.text import norm                            # noqa: E402

PORT = os.getenv("PORT", "8888")
mcp = FastMCP("playlist-lab", host="127.0.0.1", port=8877)
press = PressClient()
mb = MusicbrainzClient()
wiki = WikipediaClient()

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


def _require_lastfm(lf: LastfmClient | None) -> LastfmClient:
    if not lf:
        raise RuntimeError("Last.fm no configurado (LASTFM_API_KEY en .env): "
                           "sin él no hay mapa de géneros ni escenas.")
    return lf


def _known(sp, lf, sf) -> dict:
    return _cached("known", lambda: taste.known_artists(sp, lf, sf))


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
    géneros y sus canciones top en Spotify; su top histórico completo
    (stats.fm); `fase_actual` (artistas nuevos en el corto plazo que no están
    en el largo) y `generos_principales` agregados. Se cachea 30 min.

    Para saber si conoce a un artista concreto usa check_known, no esto: el
    perfil son solo sus tops, y escucha mucho más de lo que aparece aquí.
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


@mcp.tool()
def new_releases(months: int = 3, include_known_artists: bool = True) -> dict:
    """Discos publicados hace poco DENTRO de su órbita musical.

    Cruza los últimos lanzamientos de sus artistas, de los vecinos de estos
    (Last.fm) y de las novedades de Spotify, y los separa en `de_los_tuyos`
    (artistas que ya escucha) y `alrededor` (artistas que aún no conoce, que
    es donde suele estar lo interesante). Tarda ~20-40 s; se cachea 30 min.

    Esto es lo que una búsqueda web no te da: novedades filtradas por ÉL.
    Para contexto y crítica de esas novedades, combínalo con music_press.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    known = _cached("known", lambda: taste.known_artists(sp, lf, sf))
    key = f"new:{months}:{include_known_artists}"
    return _cached(key, lambda: discovery.new_releases(
        sp, lf, sf, known, months, include_known_artists))


@mcp.tool()
def music_press(sources: list[str] = [], since_days: int = 21,
                limit_per_source: int = 8) -> dict:
    """Artículos y reseñas recientes de la prensa musical (RSS).

    Tu conocimiento tiene fecha de corte: usa esto para saber qué se ha
    publicado y reseñado últimamente antes de hablar de novedades.
    sources (vacío = todas): """ + ", ".join(FEEDS) + """.
    Devuelve titular, fecha, resumen y enlace. Se cachea 30 min.
    """
    key = f"press:{','.join(sorted(sources))}:{since_days}:{limit_per_source}"
    return _cached(key, lambda: press.fetch(sources or None, limit_per_source,
                                            since_days))


@mcp.tool()
def verify(artist: str, album: str = "", discography: bool = False) -> dict:
    """Comprueba datos en MusicBrainz antes de afirmarlos.

    Con `artist` solo: país, años de actividad, si sigue en activo y
    etiquetas. Con `album`: fecha de la PRIMERA publicación (no la
    reedición), tipo y sello. Con discography=True: sus álbumes de estudio
    ordenados por fecha.

    Úsalo siempre que vayas a dar un año, un sello o una discografía: es
    justo lo que un modelo tiende a inventarse.
    """
    out: dict = {"artist_info": mb.find_artist(artist)}
    if album:
        out["release"] = mb.find_release(artist, album)
        if out["release"] is None:
            out["nota"] = (f"MusicBrainz no encuentra '{album}' de {artist}: "
                           "revisa el título o el nombre antes de afirmarlo.")
    if discography:
        out["discografia"] = mb.discography(artist)
    return out


# ---------- exploración ----------

@mcp.tool()
def explore_genre(genre: str, depth: int = 60, only_unknown: bool = False) -> dict:
    """Mapa de un género: qué es, de dónde viene y quién lo puebla.

    Junta la etiqueta de Last.fm (lo que la gente escucha de verdad bajo ese
    nombre, con sus artistas y álbumes), el artículo de Wikipedia (origen e
    historia) y marca cuáles ya conoce el usuario. Vale para subgéneros
    finos: "coldwave", "slowcore", "egg punk", "rock urbano".

    Lo que NO da es el canon ni las jerarquías: eso lo pones tú. La lista es
    popularidad, no calidad. Para época concreta usa explore_era.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    _require_lastfm(lf)
    key = f"genre:{genre}:{depth}:{only_unknown}"
    return _cached(key, lambda: explore.genre(
        lf, sp, wiki, mb, genre, _known(sp, lf, sf), depth, only_unknown))


@mcp.tool()
def explore_era(genre: str, year_from: int, year_to: int, limit: int = 60) -> dict:
    """Recorrer los clásicos de un género en una franja de años.

    Devuelve álbumes por FECHA DE PRIMERA PUBLICACIÓN según MusicBrainz, que
    es lo que Spotify se come (allí una reedición de 1979 figura como 2015).
    Ideal para "el post-punk del 78 al 85" o "indie español de los 90".
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    key = f"era:{genre}:{year_from}:{year_to}:{limit}"
    return _cached(key, lambda: explore.era(
        mb, sp, genre, year_from, year_to, _known(sp, lf, sf), limit))


@mcp.tool()
def discover_emerging(genres: list[str], max_popularity: int = 45,
                      limit: int = 60) -> dict:
    """Bandas emergentes: recién publicadas y aún con poca audiencia.

    Usa los filtros oficiales de Spotify tag:new (lo recién salido) y
    tag:hipster (el 10 % menos popular del catálogo), descarta lo que el
    usuario ya conoce y lo que pasa de `max_popularity` (0-100; por debajo
    de 30 es realmente pequeño).

    Pásale géneros concretos de su perfil o de explore_genre. Que algo sea
    nuevo y desconocido no lo hace bueno: cruza con music_press y filtra.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    _require_lastfm(lf)
    key = f"emerg:{','.join(genres)}:{max_popularity}"
    return _cached(key, lambda: explore.emerging(
        sp, lf, genres, _known(sp, lf, sf), max_popularity, limit))


@mcp.tool()
def find_underrated(artists: list[str]) -> dict:
    """Distingue lo de culto de lo simplemente poco escuchado.

    Para cada artista mira su audiencia en Last.fm y sus escuchas por
    oyente: mucha escucha por poca gente = público pequeño y devoto, que es
    lo que solemos llamar infravalorado. Pásale candidatos tuyos o salidos
    de explore_genre / discover_emerging.
    """
    sp, lf, sf = _clients()
    _require_lastfm(lf)
    _require_auth(sp)
    return explore.underrated(lf, sp, artists, _known(sp, lf, sf))


@mcp.tool()
def explore_scene(place: str, tag: str = "", limit: int = 40) -> dict:
    """Viajar a un sitio: qué se escucha allí y qué grupos salieron de allí.

    `place` en inglés para Last.fm ("Spain", "Japan", "Nigeria");
    MusicBrainz admite además ciudades ("Manchester", "Bilbao"). `tag`
    acota a un género dentro del lugar. Devuelve también el contexto de
    Wikipedia sobre la escena.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    _require_lastfm(lf)
    key = f"scene:{place}:{tag}:{limit}"
    return _cached(key, lambda: explore.scene(
        lf, mb, wiki, place, tag, _known(sp, lf, sf), limit))


@mcp.tool()
def artist_context(artist: str) -> dict:
    """Todo lo que se sabe de un artista, para poder explicarlo bien.

    Biografía y audiencia (Last.fm), ficha y país (MusicBrainz), formación y
    con qué otros grupos se cruza, historia (Wikipedia) y discografía real
    por fecha. Úsalo antes de contarle a alguien por qué un grupo importa o
    por dónde empezar con él, y para no inventarte fechas ni formaciones.
    """
    sp, lf, _ = _clients()
    _require_lastfm(lf)
    return _cached(f"ctx:{artist}", lambda: explore.context(lf, mb, wiki, sp, artist))


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
2. Piensa como un crítico que conoce escenas, sellos, discografías y reseñas (no como un algoritmo de similitud): busca artistas y discos que encajen con su gusto pero que probablemente no conozca, o que amplíen en una dirección coherente. Mezcla épocas y evita los nombres obvios salvo que el encargo lo pida. Tu criterio es el valor que aportas; las herramientas solo te dan los datos.
2b. Si te faltan nombres, tira de las herramientas de exploración: explore_genre para el mapa de un género, explore_era para los clásicos de una franja, explore_scene para un lugar, discover_emerging para lo que acaba de salir y find_underrated para lo de culto.
3. Si el encargo mira al presente (novedades, "lo último", este año), llama a new_releases y a music_press: tu conocimiento tiene fecha de corte y ahí es donde te equivocarás.
4. Pasa tus candidatos por check_known y descarta los conocidos (o justifica incluirlos). similar_artists de Last.fm es solo una señal más, tiende a lo obvio.
5. Antes de afirmar años, sellos o discografías, contrástalos con verify. Es preferible una frase menos a un dato inventado.
6. Verifica con resolve que todo existe en Spotify (y con album_info las duraciones si es una playlist de álbumes: ~70 min máximo por disco).
7. Presenta la propuesta con una frase por elección (por qué encaja y qué aporta) y pide confirmación.
8. Solo entonces create_playlist. Nombre corto y descriptivo."""


@mcp.prompt()
def explorar(tema: str = "") -> str:
    """Cómo guiar un viaje musical (género, época, escena o artista)."""
    return f"""Actúa como un guía musical para este usuario. Tema: {tema or '(pregunta hacia dónde quiere viajar)'}

No hagas una lista: cuenta una historia y que la lista salga de ella.

1. Sitúa el terreno. Según el tema, explore_genre (qué es y quién lo puebla), explore_era (los clásicos de una franja de años, con fechas reales), explore_scene (un lugar y lo que salió de allí) o artist_context (un artista a fondo).
2. Mira taste_profile para enganchar lo nuevo con lo que ya escucha: un viaje se entiende mejor desde casa. check_known te dice qué parte ya ha pisado.
3. Aporta lo que las herramientas no tienen: por qué ese disco cambió algo, qué escuchaba la gente antes y después, qué grupo es el eslabón. Ese relato es tu trabajo; los datos solo lo sostienen.
4. Si el tema mira al presente, discover_emerging y music_press. Si busca rarezas, find_underrated sobre tus sospechas.
5. Contrasta con verify todo año, sello o formación antes de afirmarlo.
6. Ofrece un recorrido corto (5-8 piezas o discos) con una frase por parada que diga qué escuchar en ella. Confirma antes de crear nada con create_playlist."""


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
