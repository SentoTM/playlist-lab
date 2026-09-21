"""Modos de viaje por la música: género, época, escena, emergentes y culto.

Cada función reúne datos de varias fuentes y los devuelve marcados con si el
usuario ya conoce al artista. Ninguna decide: el criterio, el canon y el
relato los pone la IA que conversa. Lo que aportan es lo que un modelo no
puede saber (qué ha escuchado él) o suele inventarse (años, audiencias).
"""
import datetime as dt
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


def era(mb: MusicbrainzClient, sp: SpotifyClient, lf: LastfmClient,
        genre_name: str, year_from: int, year_to: int, known: dict,
        limit: int = 60) -> dict:
    """Recorrer una época de un género, por dos caminos que se complementan.

    MusicBrainz da la fecha de PRIMERA publicación (Spotify fecha las
    reediciones y descoloca los clásicos), pero sus etiquetas están poco
    pobladas: lo que sale son rarezas, no el canon. Last.fm, al revés: sus
    listas por etiqueta sí reflejan lo que la gente considera importante,
    pero no traen fecha. Se devuelven las dos y el canon lo pones tú,
    verificando con `verify` los títulos concretos que vayas a afirmar.
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_mb = pool.submit(mb.releases_by_tag, genre_name, year_from, year_to, limit)
        f_lf = pool.submit(lf.tag_top_albums, genre_name, 60)

    rarezas = f_mb.result()
    for r in rarezas:
        r["lo_conoces"] = norm(r["artist"]) in known

    populares = [{"artist": a["artist"], "album": a["name"],
                  "lo_conoces": norm(a["artist"]) in known}
                 for a in f_lf.result()]

    return {
        "genero": genre_name, "desde": year_from, "hasta": year_to,
        "lo_mas_escuchado_del_genero": populares[:40],
        "rarezas_de_la_epoca": rarezas,
        "como_usarlo": (
            "'lo_mas_escuchado_del_genero' NO está filtrado por años (Last.fm "
            "no da fecha): reconoce tú cuáles caen en la franja y confírmalo "
            "con verify. 'rarezas_de_la_epoca' sí está filtrado por fecha real "
            "de edición, pero son discos poco etiquetados, no el canon. El "
            "canon de la época lo aportas tú; estas listas sirven para "
            "recordar nombres y para encontrar lo que no conocías."),
    }


def emerging(sp: SpotifyClient, lf: LastfmClient, genres: list[str],
             known: dict, max_listeners: int = 150_000, months: int = 18,
             limit: int = 40, deep_page: int = 2) -> dict:
    """Bandas emergentes: de un género, con poca audiencia y activas ahora.

    Por qué así: Spotify ha dejado de devolver `genres` y `popularity` en las
    búsquedas de apps nuevas, y `genre:` ya no filtra álbumes, así que sus
    filtros tag:new/tag:hipster solo devuelven ruido de bedroom producers.
    La pertenencia a un género la da mejor Last.fm (lo que la gente etiqueta)
    y el tamaño, su número de oyentes. `deep_page` salta las primeras páginas
    del ranking: ahí están los nombres grandes, y lo interesante está detrás.
    """
    cutoff = (dt.date.today() - dt.timedelta(days=months * 31)).isoformat()

    candidatos: list[str] = []
    for g in genres[:4]:
        for page in range(deep_page, deep_page + 2):
            for a in lf.tag_top_artists(g, 50, page):
                if norm(a["name"]) not in known:
                    candidatos.append(a["name"])
    vistos, unicos = set(), []
    for c in candidatos:
        if norm(c) not in vistos:
            vistos.add(norm(c))
            unicos.append(c)

    escaneados = unicos[:max(limit * 3, 90)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        infos = list(pool.map(lf.artist_info, escaneados))

    pequenos = [(n, i) for n, i in zip(escaneados, infos)
                if i and 0 < i.get("listeners", 0) <= max_listeners]
    # los más pequeños primero, pero exigiendo público real (evita fantasmas)
    pequenos = [x for x in pequenos if x[1]["listeners"] >= 500]
    pequenos.sort(key=lambda x: x[1]["listeners"])

    def ultimo_disco(name: str) -> dict | None:
        found = sp.search_artist(name, limit=1)
        if not found:
            return None
        albums = [a for a in sp.artist_albums(found[0]["id"], limit=10)
                  if a.get("album_type") in ("album", "single")]
        if not albums:
            return None
        ultimo = max(albums, key=lambda a: a.get("release_date", ""))
        return {"album": ultimo.get("name"), "fecha": ultimo.get("release_date"),
                "tipo": ultimo.get("album_type"), "id": ultimo.get("id")}

    with ThreadPoolExecutor(max_workers=10) as pool:
        discos = list(pool.map(ultimo_disco, [n for n, _ in pequenos[:limit]]))

    activos, dormidos, sin_spotify = [], [], []
    for (name, info), disco in zip(pequenos[:limit], discos):
        row = {"artist": info["artist"], "oyentes": info["listeners"],
               "escuchas_por_oyente": info["escuchas_por_oyente"],
               "tags": info["tags"], "ultimo_disco": disco,
               "bio": info["bio"][:280]}
        if disco is None:
            sin_spotify.append(row)
        elif (disco["fecha"] or "") >= cutoff:
            activos.append(row)
        else:
            dormidos.append(row)

    activos.sort(key=lambda r: r["ultimo_disco"]["fecha"], reverse=True)
    return {
        "generos_buscados": genres[:4],
        "embudo": {"candidatos_de_las_etiquetas": len(unicos),
                   "consultados_en_lastfm": len(escaneados),
                   "bajo_el_tope_de_oyentes": len(pequenos),
                   "con_disco_reciente": len(activos)},
        "criterio": (f"Artistas etiquetados en esos géneros en Last.fm (a partir "
                     f"de la página {deep_page} del ranking, saltando los "
                     f"grandes), con {max_listeners:,} oyentes o menos y que no "
                     f"conoces."),
        "activos": activos,
        "sin_disco_reciente": dormidos[:15],
        "no_estan_en_spotify": [r["artist"] for r in sin_spotify],
        "nota": ("'Activos' = han publicado algo desde " + cutoff + ". Que sea "
                 "pequeño y reciente no lo hace bueno: contrasta con "
                 "music_press y con tu propio criterio antes de proponerlo."),
    }


def underrated(lf: LastfmClient, sp: SpotifyClient, candidates: list[str],
               known: dict) -> dict:
    """Separa a los de culto (público pequeño y devoto) de los simplemente
    poco escuchados. Pásale una lista de artistas que sospeches infravalorados.
    """
    with ThreadPoolExecutor(max_workers=5) as pool:
        infos = list(pool.map(lf.artist_info, candidates[:25]))

    culto, discretos, conocidos, sin_datos = [], [], [], []
    for name, info in zip(candidates, infos):
        if not info or not info.get("listeners"):
            sin_datos.append(name)
            continue
        row = {"artist": info["artist"], "oyentes": info["listeners"],
               "escuchas_por_oyente": info["escuchas_por_oyente"],
               "tags": info["tags"], "lo_conoces": norm(name) in known,
               "bio": info["bio"]}
        if info["listeners"] > CULTO_MAX_LISTENERS:
            conocidos.append(row)          # grande: no cabe llamarlo infravalorado
        elif info["escuchas_por_oyente"] >= CULTO_MIN_RATIO:
            culto.append(row)              # poca gente, pero en bucle
        else:
            discretos.append(row)          # pequeño y sin público devoto

    for lst in (culto, discretos, conocidos):
        lst.sort(key=lambda r: r["escuchas_por_oyente"], reverse=True)
    return {
        "de_culto": culto,
        "pequenos_sin_publico_devoto": discretos,
        "demasiado_grandes_para_llamarlos_infravalorados": conocidos,
        "sin_datos": sin_datos,
        "criterio": (f"'De culto' = {CULTO_MIN_RATIO}+ escuchas por oyente y "
                     f"hasta {CULTO_MAX_LISTENERS:,} oyentes: poca gente, pero "
                     "en bucle. Por encima de esos oyentes no es un "
                     "descubrimiento por muy devoto que sea su público."),
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
