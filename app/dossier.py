"""Dosier de un artista: todas las señales en una sola pasada.

Evaluar un candidato pide cruzar cosas que viven en sitios distintos: cuánta
gente lo escucha y con qué intensidad, si sigue en activo, con qué sello
publica, si la prensa le hace caso, si una radio con criterio lo pincha, y
—lo más importante— si el usuario ya lo conoce o ya opinó de él.

Hacerlo a mano son seis llamadas; aquí es una. Ninguna toca Spotify.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from .clients import press
from .clients.kexp import KexpClient
from .clients.lastfm import LastfmClient
from .clients.musicbrainz import MusicbrainzClient
from .clients.wikipedia import WikipediaClient
from .text import norm

log = logging.getLogger("playlist_lab.dossier")

# Por debajo de esto un artista es realmente pequeño; por encima, ya es masivo
PEQUENO = 150_000
GRANDE = 1_000_000
DEVOTO = 8.0  # escuchas por oyente


def _seguro(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        log.warning("Parte del dosier falló (%s): %s", fn.__name__, e)
        return None


def construir(artist: str, lf: LastfmClient, mb: MusicbrainzClient,
              wiki: WikipediaClient, kexp: KexpClient,
              conocidos: dict, opiniones: dict) -> dict:
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_lf = pool.submit(_seguro, lf.artist_info, artist)
        f_wiki = pool.submit(_seguro, wiki.lookup, artist, "banda grupo musical")
        f_kexp = pool.submit(_seguro, kexp.emisiones_de, artist)
        f_prensa = pool.submit(_seguro, press.buscar_en_archivo, artist, 10)
        f_mb = pool.submit(_seguro, mb.find_artist, artist)

    info = f_lf.result() or {}
    ficha = f_mb.result() or {}
    # los sellos van después: MusicBrainz solo admite una petición por segundo
    sellos = _seguro(mb.sellos_de, artist) or []
    emisiones = f_kexp.result() or []
    prensa_items = f_prensa.result() or []

    oyentes = info.get("listeners") or 0
    ratio = info.get("escuchas_por_oyente") or 0
    clave = norm(artist)

    senales = []
    if oyentes:
        if oyentes < PEQUENO:
            senales.append(f"pequeño ({oyentes:,} oyentes en Last.fm)")
        elif oyentes > GRANDE:
            senales.append(f"grande ({oyentes:,} oyentes): no es un descubrimiento")
        if ratio >= DEVOTO and oyentes < GRANDE:
            senales.append(f"público devoto ({ratio} escuchas por oyente)")
    else:
        senales.append("sin datos de audiencia en Last.fm")
    if ficha.get("activo_desde"):
        senales.append(f"en activo desde {ficha['activo_desde']}"
                       + (" (separados)" if ficha.get("separado") else ""))
    if emisiones:
        senales.append(f"KEXP lo ha pinchado {len(emisiones)} veces")
    if prensa_items:
        senales.append(f"{len(prensa_items)} menciones en la prensa archivada")
    if sellos:
        senales.append("publica con " + ", ".join(sellos[:3]))

    relacion = conocidos.get(clave)
    if not relacion and lf.username:
        # Los tops solo recogen a los más escuchados: alguien que escuchas
        # ahora mismo por primera vez no está ahí (pasó con Aiko el grupo,
        # que sonaba mientras el dossier decía "no lo conoces").
        plays = _seguro(lf.user_artist_playcount, artist) or 0
        if plays:
            relacion = {"lastfm_plays": plays}
    opinion = opiniones.get(artist) or opiniones.get(clave)
    if opinion:
        senales.insert(0, f"YA OPINASTE: {opinion.get('veredicto')}")
    elif relacion:
        senales.insert(0, "ya lo conoces")

    return {
        "artist": info.get("artist") or artist,
        "resumen_de_senales": senales,
        "lo_conoces": bool(relacion),
        "tu_relacion": {k: v for k, v in (relacion or {}).items() if k != "artist"} or None,
        "tu_opinion": opinion,
        "audiencia": {"oyentes": oyentes, "escuchas_por_oyente": ratio,
                      "etiquetas": info.get("tags")},
        "ficha": ficha or None,
        "sellos": sellos,
        "bio": info.get("bio"),
        "wikipedia": f_wiki.result(),
        "emitido_en_kexp": emisiones[:8],
        "prensa": [{"medio": i.get("source"), "titular": i.get("title"),
                    "fecha": i.get("date"), "url": i.get("url")}
                   for i in prensa_items],
        "similares_lastfm": info.get("similares"),
        "nota": ("Ausencia de señales no es mala señal: la prensa archivada "
                 "solo tiene lo que hemos ido recogiendo, y KEXP es una sola "
                 "emisora con sesgo anglosajón. Pesa esto con tu criterio."),
    }
