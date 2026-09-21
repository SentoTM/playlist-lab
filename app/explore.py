"""Modos de viaje por la música: género, época, escena, emergentes y culto.

Cada función reúne datos de varias fuentes y los devuelve marcados con si el
usuario ya conoce al artista. Ninguna decide: el criterio, el canon y el
relato los pone la IA que conversa. Lo que aportan es lo que un modelo no
puede saber (qué ha escuchado él) o suele inventarse (años, audiencias).
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from .clients.lastfm import LastfmClient
from .clients.musicbrainz import MusicbrainzClient
from .clients.spotify import SpotifyClient
from .clients.wikipedia import WikipediaClient
from .text import norm

log = logging.getLogger("playlist_lab.explore")

# Un artista con pocos oyentes pero muchas escuchas por oyente es de culto,
# no desconocido: alguien lo escucha en bucle.
CULTO_MIN_RATIO = 8.0
CULTO_MAX_LISTENERS = 300_000


def _mark(name: str, known: dict) -> dict:
    e = known.get(norm(name))
    return {"artist": name, "lo_conoces": bool(e),
            **({"tu_relacion": {k: v for k, v in e.items() if k != "artist"}} if e else {})}


def _album_row(a: dict, known: dict) -> dict:
    artist = (a.get("artists") or [{}])[0].get("name", "")
    return {"artist": artist, "album": a.get("name", ""),
            "date": a.get("release_date", ""), "type": a.get("album_type"),
            "n_tracks": a.get("total_tracks"), "id": a.get("id"),
            "lo_conoces": norm(artist) in known}


def genre(lf: LastfmClient, sp: SpotifyClient, wiki: WikipediaClient,
          mb: MusicbrainzClient, name: str, known: dict,
          depth: int = 60, only_unknown: bool = False) -> dict:
    """Mapa de un género: qué es, quién lo define, qué escuchan de él.

    Mezcla la etiqueta de Last.fm (lo que la gente realmente escucha bajo ese
    nombre) con el artículo de Wikipedia (historia y origen) y con el
    catálogo de Spotify. Lo que falta aquí —el canon, las jerarquías, lo
    imprescindible— lo pone tu criterio.
    """
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_info = pool.submit(lf.tag_info, name)
        f_artists = pool.submit(lf.tag_top_artists, name, depth)
        f_albums = pool.submit(lf.tag_top_albums, name, 40)
        f_wiki = pool.submit(wiki.lookup, name, "género musical")

    artistas = [_mark(a["name"], known) for a in f_artists.result()]
    if only_unknown:
        artistas = [a for a in artistas if not a["lo_conoces"]]
    albums = [{"artist": a["artist"], "album": a["name"],
               "lo_conoces": norm(a["artist"]) in known}
              for a in f_albums.result()]

    return {
        "genero": name,
        "definicion": f_info.result(),
        "contexto": f_wiki.result(),
        "artistas_del_genero": artistas,
        "albumes_del_genero": albums[:30],
        "nota": ("La lista viene de lo que la gente etiqueta y escucha en "
                 "Last.fm: es popularidad, no calidad ni canon. Úsala como "
                 "mapa y pon tú las jerarquías."),
    }


def era(mb: MusicbrainzClient, sp: SpotifyClient, genre_name: str,
        year_from: int, year_to: int, known: dict, limit: int = 60) -> dict:
    """Recorrer una época: álbumes de un género en una franja de años.

    Usa MusicBrainz porque da la fecha de la PRIMERA publicación; Spotify
    devuelve la de la reedición y hunde los clásicos en el año equivocado.
    """
    releases = mb.releases_by_tag(genre_name, year_from, year_to, limit)
    for r in releases:
        r["lo_conoces"] = norm(r["artist"]) in known
    return {
        "genero": genre_name, "desde": year_from, "hasta": year_to,
        "albumes": releases,
        "nota": ("Fechas de primera publicación (MusicBrainz), no de "
                 "reedición. Verifica en Spotify con resolve antes de "
                 "montar nada: no todo está disponible."),
    }


def emerging(sp: SpotifyClient, lf: LastfmClient, genres: list[str],
             known: dict, max_popularity: int = 45, limit: int = 60) -> dict:
    """Bandas emergentes: publicación reciente y audiencia todavía pequeña.

    Combina los filtros oficiales de Spotify (tag:new para lo recién salido,
    tag:hipster para el 10 % menos popular del catálogo) y descarta lo que ya
    conoces y lo que ya es grande.
    """
    def fetch(g: str) -> list[dict]:
        out = sp.search_albums_filtered(genre=g, new=True, limit=40)
        out += sp.search_albums_filtered(genre=g, hipster=True, limit=40)
        return out

    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(fetch, genres[:6]))

    seen, rows, artist_ids = set(), [], {}
    for albums in batches:
        for a in albums:
            row = _album_row(a, known)
            if not row["artist"] or row["lo_conoces"] or a.get("id") in seen:
                continue
            seen.add(a.get("id"))
            rows.append(row)
            aid = (a.get("artists") or [{}])[0].get("id")
            if aid:
                artist_ids.setdefault(aid, []).append(row)

    for art in sp.artists_by_id(list(artist_ids)):
        for row in artist_ids.get(art["id"], []):
            row["popularidad"] = art.get("popularity")
            row["seguidores"] = (art.get("followers") or {}).get("total")
            row["generos"] = art.get("genres", [])[:4]

    rows = [r for r in rows
            if r.get("popularidad") is None or r["popularidad"] <= max_popularity]
    rows.sort(key=lambda r: (r.get("popularidad") or 99, r["date"]), reverse=False)
    return {
        "generos_buscados": genres[:6], "max_popularidad": max_popularity,
        "candidatos": rows[:limit],
        "nota": ("Popularidad de Spotify 0-100: por debajo de 30 es "
                 "realmente pequeño. Que sea nuevo y desconocido no lo hace "
                 "bueno; filtra tú y contrasta con music_press."),
    }


def underrated(lf: LastfmClient, sp: SpotifyClient, candidates: list[str],
               known: dict) -> dict:
    """Separa a los de culto (público pequeño y devoto) de los simplemente
    poco escuchados. Pásale una lista de artistas que sospeches infravalorados.
    """
    with ThreadPoolExecutor(max_workers=5) as pool:
        infos = list(pool.map(lf.artist_info, candidates[:25]))

    culto, discretos, sin_datos = [], [], []
    for name, info in zip(candidates, infos):
        if not info or not info.get("listeners"):
            sin_datos.append(name)
            continue
        row = {"artist": info["artist"], "oyentes": info["listeners"],
               "escuchas_por_oyente": info["escuchas_por_oyente"],
               "tags": info["tags"], "lo_conoces": norm(name) in known,
               "bio": info["bio"]}
        es_culto = (info["escuchas_por_oyente"] >= CULTO_MIN_RATIO
                    and info["listeners"] <= CULTO_MAX_LISTENERS)
        (culto if es_culto else discretos).append(row)

    culto.sort(key=lambda r: r["escuchas_por_oyente"], reverse=True)
    return {
        "de_culto": culto, "poco_escuchados": discretos, "sin_datos": sin_datos,
        "criterio": (f"'De culto' = {CULTO_MIN_RATIO}+ escuchas por oyente y "
                     f"menos de {CULTO_MAX_LISTENERS:,} oyentes: poca gente, "
                     "pero en bucle."),
    }


def scene(lf: LastfmClient, mb: MusicbrainzClient, wiki: WikipediaClient,
          place: str, tag: str, known: dict, limit: int = 40) -> dict:
    """Viajar a un sitio: qué se escucha allí y qué grupos salieron de allí.

    `place` en inglés para Last.fm ('Spain', 'Japan'); MusicBrainz admite
    también ciudades ('Manchester', 'Bilbao').
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_geo = pool.submit(lf.geo_top_artists, place, limit)
        f_mb = pool.submit(mb.artists_from, place, tag, limit)
        f_wiki = pool.submit(wiki.lookup, f"{tag} {place}".strip(), "música escena")

    de_alli = []
    for a in f_mb.result():
        de_alli.append({**a, "lo_conoces": norm(a["artist"]) in known})
    return {
        "lugar": place, "etiqueta": tag or None,
        "contexto": f_wiki.result(),
        "lo_mas_escuchado_alli": [_mark(a["name"], known) for a in f_geo.result()][:25],
        "de_alli_segun_musicbrainz": de_alli,
        "nota": ("'Lo más escuchado allí' es el gusto mayoritario del país "
                 "en Last.fm, no la escena local; para eso mira la segunda "
                 "lista y el contexto."),
    }


def context(lf: LastfmClient, mb: MusicbrainzClient, wiki: WikipediaClient,
            sp: SpotifyClient, artist: str) -> dict:
    """Todo lo que se sabe de un artista, para contarlo bien.

    Biografía y audiencia (Last.fm), ficha y formación (MusicBrainz),
    historia (Wikipedia) y discografía real por fecha. Con esto puedes
    explicar de dónde viene, con quién se cruza y por dónde empezar.
    """
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_lf = pool.submit(lf.artist_info, artist)
        f_mb = pool.submit(mb.find_artist, artist)
        f_rel = pool.submit(mb.artist_relations, artist)
        f_wiki = pool.submit(wiki.lookup, artist, "banda grupo musical")
        f_disc = pool.submit(mb.discography, artist)

    return {
        "artist": artist,
        "lastfm": f_lf.result(),
        "ficha": f_mb.result(),
        "formacion_y_parentesco": f_rel.result(),
        "wikipedia": f_wiki.result(),
        "discografia": f_disc.result(),
        "nota": ("Fechas y formación vienen de MusicBrainz: son fiables. "
                 "Si algo no aparece aquí, no lo afirmes."),
    }
