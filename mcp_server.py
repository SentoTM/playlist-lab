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

from app import cache, discovery, explore, jobs, library, notes, taste  # noqa: E402
from app.clients.lastfm import LastfmClient          # noqa: E402
from app.clients.musicbrainz import MusicbrainzClient  # noqa: E402
from app.clients.press import FEEDS, PressClient     # noqa: E402
from app.clients.spotify import SpotifyClient, SpotifyRateLimited  # noqa: E402
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


BIBLIOTECA_TTL = 7 * 24 * 3600   # cambia despacio y cuesta ~18 peticiones
CONOCIDOS_TTL = 12 * 3600
PERFIL_TTL = 6 * 3600


def _biblioteca(sp) -> dict:
    """La biblioteca guardada, cacheada en disco: es lo único que pedimos a
    Spotify para el perfil, y es lo que nadie más tiene."""
    def traer():
        try:
            return taste.library(sp)
        except SpotifyRateLimited:
            return {}
    return cache.recordar("biblioteca", BIBLIOTECA_TTL, traer) or {}


def _known(sp, lf, sf) -> dict:
    """Lo que ya conoce, más lo que ha dicho que no quiere volver a ver.

    Los vetados entran aquí a propósito: para el filtrado son equivalentes a
    'ya lo conoce', así que ninguna herramienta de descubrimiento los
    propondrá por su cuenta.
    """
    # Sin cuota de Spotify: stats.fm + Last.fm + la biblioteca ya cacheada
    conocidos = dict(cache.recordar(
        "known", CONOCIDOS_TTL,
        lambda: taste.known_artists(sf, lf, _biblioteca(sp))))
    artistas = notes.cargar()["artistas"]
    for clave, veredicto in notes.vetados().items():
        conocidos.setdefault(clave, {"artist": artistas[clave]["artista"]})
        conocidos[clave]["descartado_por_ti"] = veredicto
    return conocidos


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
    avisos = sf.privacy_warnings() if sf else []
    faltan = sp.missing_scopes() if sp.authenticated else []
    if faltan:
        avisos.append(
            "Al token de Spotify le faltan permisos (" + ", ".join(faltan) +
            "): dile al usuario que entre en http://127.0.0.1:8888, pulse "
            "'salir' y vuelva a iniciar sesión. Mientras tanto, no uses "
            "now_playing ni cuentes con los artistas que sigue.")
    bloqueo = SpotifyClient.segundos_bloqueado()
    if bloqueo:
        avisos.append(
            f"Spotify tiene limitada la app {bloqueo // 60} min más (cuota del "
            "modo desarrollo). Evita consultas grandes hasta entonces; lo "
            "cacheado sigue funcionando.")
    return {
        "spotify_configured": bool(os.getenv("SPOTIFY_CLIENT_ID")),
        "spotify_session": user,
        "lastfm": bool(lf), "statsfm": bool(sf),
        "permisos_que_faltan": faltan,
        "spotify_bloqueado_segundos": bloqueo,
        "peticiones_a_spotify_en_esta_sesion": SpotifyClient.peticiones,
        "veces_limitado": SpotifyClient.limitaciones,
        "cache_en_disco": cache.estado(),
        "warnings": avisos,
    }


@mcp.tool()
def taste_profile() -> dict:
    """Perfil de gustos del usuario: EMPIEZA SIEMPRE POR AQUÍ antes de proponer.

    Devuelve, por periodo (últimas semanas / últimos meses / siempre), sus
    artistas y canciones más escuchados con géneros y número de escuchas; su
    biblioteca guardada (otra señal: guardar es decidir, repetir no);
    `fase_actual` (quién suena ahora y no venía de largo, la pista más útil)
    y `generos_principales`.

    Sale de stats.fm, que recoge todo su historial de Spotify, así que NO
    gasta cuota de Spotify. Se cachea en disco 6 h.

    Para saber si conoce a un artista concreto usa check_known, no esto: el
    perfil son solo sus tops, y escucha mucho más de lo que aparece aquí.
    """
    sp, lf, sf = _clients()
    if not sf:
        raise RuntimeError("stats.fm no está configurado y es la fuente del "
                           "perfil (STATSFM_USERNAME en .env).")
    return cache.recordar(
        "profile", PERFIL_TTL,
        lambda: taste.taste_profile(sf, _biblioteca(sp)))


@mcp.tool()
def my_library() -> dict:
    """Lo que el usuario ha GUARDADO en Spotify: canciones y álbumes.

    Señal distinta de los tops: guardar es una decisión deliberada, repetir
    no. Aquí salen discos que aprecia aunque no suenen a diario y artistas
    que ningún top muestra. Mira también qué ha guardado últimamente: dice
    hacia dónde va ahora mismo. Se cachea 30 min.
    """
    sp, _, _ = _clients()
    _require_auth(sp)
    return _biblioteca(sp)


@mcp.tool()
def my_playlists(mine_only: bool = True) -> list:
    """Las playlists del usuario: cómo organiza él la música.

    Los nombres y tamaños dicen para qué usa cada cosa (trabajar, correr, un
    género, un viaje). Útil antes de crear una nueva: para no duplicar, para
    seguir su forma de nombrarlas, o para proponer ampliar una existente.
    Con playlist_contents puedes ver qué hay dentro de una.
    """
    sp, _, _ = _clients()
    _require_auth(sp)
    return _cached(f"playlists:{mine_only}", lambda: taste.playlists(sp, mine_only))


@mcp.tool()
def playlist_contents(playlist_id: str, limit: int = 100) -> dict:
    """Qué hay dentro de una playlist suya (id de my_playlists).

    Sirve para entender un contexto concreto ("mi playlist de currar") antes
    de ampliarla o de hacer una hermana.
    """
    sp, _, _ = _clients()
    _require_auth(sp)
    tracks = sp.playlist_tracks(playlist_id, limit)
    return {"n": len(tracks), "tracks": [
        {"artist": (t.get("artists") or [{}])[0].get("name"),
         "title": t.get("name"),
         "album": (t.get("album") or {}).get("name")} for t in tracks]}


@mcp.tool()
def now_playing() -> dict:
    """Qué está sonando ahora mismo, si hay algo.

    Para encargos del tipo "pon algo que siga a esto". Requiere haber hecho
    login después de añadir el permiso user-read-currently-playing.
    """
    sp, _, _ = _clients()
    _require_auth(sp)
    t = sp.currently_playing()
    if not t:
        return {"sonando": None,
                "nota": ("Nada sonando, o falta el permiso: vuelve a iniciar "
                         "sesión en http://127.0.0.1:8888 para concederlo.")}
    return {"sonando": {"artist": (t.get("artists") or [{}])[0].get("name"),
                        "title": t.get("name"),
                        "album": (t.get("album") or {}).get("name"),
                        "uri": t.get("uri")}}


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

    Devuelve por artista: known (bool) y evidencia (puesto en sus tops de
    Spotify, canciones o álbumes guardados, si lo sigue, scrobbles en
    Last.fm, streams en stats.fm). Con deep=True
    consulta además en Last.fm los que no aparecen en ningún top (detecta
    artistas escuchados poco pero escuchados).
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    known = _known(sp, lf, sf)
    opiniones = notes.para(artists)
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
        if name in opiniones:
            op = opiniones[name]
            out[name]["tu_opinion"] = {k: v for k, v in op.items()
                                       if k != "artista"}
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
        known = _known(sp, lf, sf)
        sims = [s for s in sims if norm(s["name"]) not in known]
    return sims[:limit]


@mcp.tool()
def search(query: str, kind: str = "album", limit: int = 5) -> list:
    """Busca en Spotify. kind: album | track | artist.

    Filtros útiles: 'album:Nombre artist:Grupo', 'year:2020-2024'. OJO:
    'genre:' ya no filtra y los campos popularity/genres vienen vacíos para
    apps nuevas (deprecación de Spotify). Para explorar por género usa
    explore_genre o discover_emerging."""
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

    NO gasta cuota de Spotify: pregunta a MusicBrainz, que da la fecha de
    primera edición y solo limita a una petición por segundo. A cambio tarda
    (~30 s) y algún lanzamiento de los últimos días puede no estar catalogado
    todavía. Se calcula en segundo plano: si la respuesta dice
    `vuelve_a_llamar`, llama otra vez con los MISMOS parámetros.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    key = f"new:{months}:{include_known_artists}"

    def calcular(paso):
        paso("leyendo lo que ya conoces (stats.fm, Last.fm y tu biblioteca)")
        known = _known(sp, lf, sf)
        return discovery.new_releases(sp, lf, sf, known, months,
                                      include_known_artists, paso=paso, mb=mb)

    return jobs.run_or_wait(key, calcular)


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


# ---------- cómo quiere que le propongan ----------

@mcp.tool()
def curation_guide() -> dict:
    """CÓMO escuchar y proponerle música. Léelo antes de curar nada.

    No es una lista de géneros: es su criterio (personalidad por encima de
    ejecución, qué entiende por "garra"), sus reglas prácticas (experimental
    solo con punto de anclaje, no repetir siempre el mismo eje, el directo
    cuenta), el formato de "menú de cinco" que prefiere, las cuatro
    dimensiones con que etiquetar una propuesta y —importante— cómo mide el
    éxito: una recomendación que no le gusta pero le hace entender por qué un
    disco importa es un acierto, no un fallo.

    Vive en datos/perfil.md y él lo edita a mano cuando cambia de idea.
    """
    ruta = Path(__file__).resolve().parent / "datos" / "perfil.md"
    if not ruta.exists():
        return {"error": "No hay datos/perfil.md todavía."}
    return {"guia": ruta.read_text(encoding="utf-8")}


# ---------- tus opiniones ----------

@mcp.tool()
def remember(tipo: str, sujeto: str, veredicto: str = "", nota: str = "",
             album: str = "") -> dict:
    """Guarda lo que el usuario opina. ÚSALO EN CUANTO LO DIGA, sin esperar.

    Los datos de escucha no distinguen un disco que odió de uno que se sabe
    de memoria: solo su juicio lo dice, y se pierde al cerrar la
    conversación si no se guarda aquí.

    tipo: "artista", "album" (pasa también `album`) o "general" (una
    preferencia suya: "las playlists de más de hora y media no las oigo").
    veredicto: "me encanta", "me gusta", "sin pena ni gloria", "no es para mí
    pero lo entiendo", "no es lo mío", "nunca más", "pendiente" o
    "escuchado". Ojo: para él una recomendación NO fracasa por no gustarle,
    así que "sin pena ni gloria" y "no es para mí pero lo entiendo" no
    descartan nada (siguen valiendo para una segunda escucha). Solo "nunca
    más" y "no es lo mío" sacan al artista del descubrimiento.
    `nota`: con sus palabras y el motivo, que es lo que sirve después.

    Ante la duda de si merece guardarse, guárdalo: cuesta poco y no
    guardarlo significa perderlo.
    """
    try:
        entrada = notes.anotar(tipo, sujeto, veredicto, nota, album)
    except ValueError as e:
        return {"error": str(e)}
    cache.olvidar("known")  # el veto cambia lo que es proponible
    return {"guardado": entrada,
            "veredictos_posibles": notes.VEREDICTOS if not veredicto else None}


@mcp.tool()
def my_notes() -> dict:
    """Todo lo que el usuario ha opinado hasta ahora.

    CONSÚLTALO ANTES DE PROPONER NADA, junto con taste_profile: aquí está
    lo que ya rechazó (para no repetirlo), lo que le encantó (buenas
    referencias para buscar parecidos) y lo que dejó pendiente de escuchar.
    """
    return notes.listar()


@mcp.tool()
def forget_note(tipo: str, sujeto: str, album: str = "") -> dict:
    """Borra una nota cuando el usuario cambia de opinión.

    tipo: "artista" o "album". Un veto retirado vuelve a hacer proponible a
    ese artista.
    """
    borrado = notes.olvidar(tipo, sujeto, album)
    cache.olvidar("known")
    return {"borrado": borrado,
            "nota": "No había nota que borrar" if not borrado else "Hecho"}


@mcp.tool()
def artist_releases(artist: str, limit: int = 20) -> dict:
    """Discografía en Spotify de un artista, de lo más nuevo a lo más viejo.

    Útil para "¿qué ha sacado últimamente?" o "¿por dónde empiezo?". Para
    fechas de PRIMERA edición (sin reediciones) usa verify: Spotify fecha
    las reediciones y confunde los clásicos.
    """
    sp, _, _ = _clients()
    _require_auth(sp)
    found = sp.search_artist(artist, limit=1)
    if not found:
        return {"error": f"No encuentro a {artist} en Spotify"}
    albums = sp.artist_albums(found[0]["id"], limit=limit, artist_name=artist)
    return {"artist": found[0].get("name"), "n": len(albums), "albumes": [
        {"album": a.get("name"), "fecha": a.get("release_date"),
         "tipo": a.get("album_type"), "canciones": a.get("total_tracks"),
         "id": a.get("id")} for a in albums]}


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

    Devuelve dos listas que se complementan: lo más escuchado del género en
    Last.fm (refleja el canon, pero sin fecha) y las rarezas de esa franja
    según MusicBrainz (fecha de PRIMERA edición, que es lo que Spotify se
    come: allí una reedición de 1979 figura como 2015).

    El canon de la época lo pones tú; esto sirve para recordar nombres y
    sacar lo que no conocía. Confirma con verify los títulos que afirmes.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    key = f"era:{genre}:{year_from}:{year_to}:{limit}"
    _require_lastfm(lf)
    return _cached(key, lambda: explore.era(
        mb, sp, lf, genre, year_from, year_to, _known(sp, lf, sf), limit))


@mcp.tool()
def discover_emerging(genres: list[str], max_listeners: int = 150000,
                      months: int = 18, limit: int = 40,
                      deep_page: int = 2) -> dict:
    """Bandas emergentes de unos géneros: pequeñas y activas ahora.

    Toma los artistas etiquetados en esos géneros en Last.fm saltando las
    primeras páginas del ranking (donde están los grandes), se queda con los
    que tienen `max_listeners` oyentes o menos y no conoce el usuario, y mira
    en Spotify si han publicado algo en los últimos `months` meses.

    Sube `deep_page` (3, 4, 5…) para bajar más en el pozo. Baja
    `max_listeners` a 30000-50000 para rarezas de verdad.

    No usa los filtros de Spotify a propósito: `genre:` ya no funciona en
    búsqueda de álbumes para apps nuevas y tag:new/tag:hipster devuelven
    ruido. Cruza el resultado con music_press antes de recomendar nada.

    LENTO: consulta más de cien artistas. Se calcula en segundo plano, así
    que si la respuesta dice `vuelve_a_llamar`, llama otra vez con los MISMOS
    parámetros para recoger el resultado.
    """
    sp, lf, sf = _clients()
    _require_auth(sp)
    _require_lastfm(lf)
    key = f"emerg:{','.join(genres)}:{max_listeners}:{months}:{deep_page}:{limit}"

    def calcular():
        return explore.emerging(sp, lf, genres, _known(sp, lf, sf),
                                max_listeners, months, limit, deep_page)

    return jobs.run_or_wait(key, calcular)


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
1. Llama a curation_guide, taste_profile y my_notes, y lee con calma: fase actual, géneros principales, qué escucha ahora vs. históricamente, y sobre todo qué ya ha juzgado (lo vetado no se propone; lo que le encanta es buena referencia para buscar parecidos).
2. Piensa como un crítico que conoce escenas, sellos, discografías y reseñas (no como un algoritmo de similitud): busca artistas y discos que encajen con su gusto pero que probablemente no conozca, o que amplíen en una dirección coherente. Mezcla épocas y evita los nombres obvios salvo que el encargo lo pida. Tu criterio es el valor que aportas; las herramientas solo te dan los datos.
2b. Si te faltan nombres, tira de las herramientas de exploración: explore_genre para el mapa de un género, explore_era para los clásicos de una franja, explore_scene para un lugar, discover_emerging para lo que acaba de salir y find_underrated para lo de culto.
3. Si el encargo mira al presente (novedades, "lo último", este año), llama a new_releases y a music_press: tu conocimiento tiene fecha de corte y ahí es donde te equivocarás.
4. Pasa tus candidatos por check_known y descarta los conocidos (o justifica incluirlos). similar_artists de Last.fm es solo una señal más, tiende a lo obvio.
5. Antes de afirmar años, sellos o discografías, contrástalos con verify. Es preferible una frase menos a un dato inventado.
6. Verifica con resolve que todo existe en Spotify (y con album_info las duraciones si es una playlist de álbumes: ~70 min máximo por disco).
7. Presenta la propuesta con una frase por elección (por qué encaja y qué aporta) y pide confirmación.
8. Solo entonces create_playlist. Nombre corto y descriptivo.
9. Durante toda la conversación, cada vez que opine sobre algo ("esto me encanta", "de estos no me pongas más", "me lo apunto"), guárdalo con remember en ese momento. Es lo que hace que la próxima vez no empecemos de cero."""


@mcp.prompt()
def explorar(tema: str = "") -> str:
    """Cómo guiar un viaje musical (género, época, escena o artista)."""
    return f"""Actúa como un guía musical para este usuario. Tema: {tema or '(pregunta hacia dónde quiere viajar)'}

No hagas una lista: cuenta una historia y que la lista salga de ella.

1. Sitúa el terreno. Según el tema, explore_genre (qué es y quién lo puebla), explore_era (los clásicos de una franja de años, con fechas reales), explore_scene (un lugar y lo que salió de allí) o artist_context (un artista a fondo).
2. Mira curation_guide, taste_profile y my_notes para enganchar lo nuevo con lo que ya escucha y no repetir lo que ya descartó: un viaje se entiende mejor desde casa. check_known te dice qué parte ya ha pisado y qué opinó.
3. Aporta lo que las herramientas no tienen: por qué ese disco cambió algo, qué escuchaba la gente antes y después, qué grupo es el eslabón. Ese relato es tu trabajo; los datos solo lo sostienen.
4. Si el tema mira al presente, discover_emerging y music_press. Si busca rarezas, find_underrated sobre tus sospechas.
5. Contrasta con verify todo año, sello o formación antes de afirmarlo.
6. Ofrece un recorrido corto (5-8 piezas o discos) con una frase por parada que diga qué escuchar en ella. Confirma antes de crear nada con create_playlist.
7. Guarda con remember lo que vaya opinando por el camino, incluido lo que le apetece escuchar más adelante ("pendiente")."""


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
