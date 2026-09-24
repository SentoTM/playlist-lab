"""Búsqueda, resolución y creación en Spotify.

La IA propone en texto ("Artista – Canción", "Artista – Álbum"); aquí se
convierte eso en URIs verificadas y se crea la playlist. Siempre se informa
de lo que no se ha podido resolver para que se corrija en conversación.
"""
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from .clients.spotify import SpotifyClient
from . import cache
from .text import norm, parse_item

# Un disco "normal" rara vez pasa de esto; por encima suele ser una edición
# ampliada o un recopilatorio colado (Cut de The Slits en su deluxe de 130
# minutos, Super Ape convertido en una antología de 133).
MINUTOS_SOSPECHOSOS = 70

# Palabras que delatan una edición que NO es la original
_EDICION = re.compile(
    r"\b(deluxe|expanded|anniversary|remaster(ed)?|edition|edici[oó]n|collector|"
    r"bonus|reissue|anthology|antolog[ií]a|best of|greatest hits|complete|"
    r"box set|singles|recopilatorio|demos|sessions)\b", re.I)


def _plano(s: str) -> str:
    """Para comparar y para buscar: sin tildes, sin apóstrofes ni signos.

    Spotify escribe a veces el apóstrofe tipográfico (’) y otras el recto
    ('), y "Sinéad O'Brien" no casaba con "Sinéad O’Brien".
    """
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[’'`´]", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _artist_matches(candidate: dict, artist: str) -> bool:
    names = [_plano(a.get("name", "")) for a in candidate.get("artists", [])]
    buscado = _plano(artist)
    return any(n == buscado for n in names) or any(
        buscado and n and (buscado in n or n in buscado) for n in names)


def find_track(sp: SpotifyClient, artist: str, title: str) -> dict | None:
    """Canción exacta (artista + título) o None. Prefiere versiones de estudio."""
    results = sp.search_track(f'track:"{title}" artist:"{artist}"', limit=5) \
        or sp.search_track(f"{title} {artist}", limit=5)
    good = [t for t in results if _artist_matches(t, artist)]
    if not good:
        return None
    good.sort(key=lambda t: (("live" in norm(t.get("name", ""))
                              and "live" not in norm(title)),
                             -t.get("popularity", 0)))
    return good[0]


def find_artist(sp: SpotifyClient, nombre: str) -> tuple[dict | None, str | None]:
    """El artista pedido, o None si Spotify no lo tiene.

    Spotify, cuando no encuentra a alguien, devuelve lo más parecido que
    tenga: buscando "Las Petunias" devolvía Mala Gestión, y buscando
    "Melenas", Hinds. Coger el primer resultado a ciegas colaba la
    discografía de otro grupo. Ahora se exige que el nombre case.

    Devuelve (artista, aviso). Si no casa, artista es None y el aviso dice
    qué devolvió Spotify en su lugar.
    """
    resultados = sp.search_artist(nombre, limit=5)
    buscado = _plano(nombre)
    for a in resultados:
        if _plano(a.get("name", "")) == buscado:
            return a, None
    for a in resultados:  # "The X" / "X", "X & The Y"...
        n = _plano(a.get("name", ""))
        if buscado and n and (n == f"the {buscado}" or buscado == f"the {n}"):
            return a, None
    if resultados:
        return None, (f"'{nombre}' no está en Spotify (o no con ese nombre): la "
                      f"búsqueda devolvió '{resultados[0].get('name')}', que es "
                      "otro artista.")
    return None, f"'{nombre}' no está en Spotify."


def _candidatos_album(sp: SpotifyClient, artist: str, album: str) -> list[dict]:
    """Búsquedas de más estricta a más laxa, hasta que algo case con el artista.

    La última prueba sin comillas y sin signos rescata títulos con apóstrofes
    o tildes, que con la sintaxis de campos de Spotify a veces no aparecen.
    """
    consultas = [f'album:"{album}" artist:"{artist}"',
                 f"{album} {artist}",
                 f"{_plano(album)} {_plano(artist)}",
                 _plano(album)]
    for q in consultas:
        buenos = [a for a in sp.search_album(q, limit=10) if _artist_matches(a, artist)]
        if buenos:
            return buenos
    return []


def find_album(sp: SpotifyClient, artist: str, album: str) -> dict | None:
    """El álbum pedido, prefiriendo la EDICIÓN ORIGINAL.

    Antes cogía la primera coincidencia y se colaban deluxes y antologías.
    Ahora ordena por: título que casa, que sea álbum (no recopilatorio), que
    no tenga pinta de reedición (salvo que se pida), menos pistas y, a
    igualdad, la fecha más antigua, que es la de la edición original.
    """
    good = _candidatos_album(sp, artist, album)
    if not good:
        return None
    pide_edicion = bool(_EDICION.search(album))

    def clave(a: dict):
        nombre = a.get("name", "")
        casa = _plano(norm(nombre)) == _plano(norm(album))
        es_edicion = bool(_EDICION.search(nombre))
        # si pide una edición concreta, que la tenga; si no, que no la tenga
        desajuste = es_edicion != pide_edicion
        return (not casa, desajuste, a.get("album_type") != "album",
                a.get("total_tracks") or 99, a.get("release_date") or "9999")

    good.sort(key=clave)
    elegido = dict(good[0])
    elegido["_alternativas"] = len(good) - 1
    return elegido


def album_details(sp: SpotifyClient, album_id: str) -> dict:
    full = sp.album(album_id)
    tracks = full.get("tracks", {}).get("items", [])
    return {
        "album": full.get("name"),
        "artist": (full.get("artists") or [{}])[0].get("name"),
        "year": (full.get("release_date") or "")[:4],
        "n_tracks": len(tracks),
        "minutes": round(sum(t.get("duration_ms", 0) for t in tracks) / 60000),
        "tracks": [t.get("name") for t in tracks],
        "uris": [t.get("uri") for t in tracks if t.get("uri")],
        "id": full.get("id"),
        "url": (full.get("external_urls") or {}).get("spotify"),
    }


def _track_summary(t: dict) -> dict:
    return {
        "artist": (t.get("artists") or [{}])[0].get("name"),
        "title": t.get("name"),
        "album": (t.get("album") or {}).get("name"),
        "year": ((t.get("album") or {}).get("release_date") or "")[:4],
        "minutes": round(t.get("duration_ms", 0) / 60000, 1),
        "popularity": t.get("popularity"),
        "uri": t.get("uri"),
    }


DIAS_MEMO = 7


def _memo(clave: str, fn):
    """Resultado de Spotify para un elemento, guardado 7 días. Lo típico es
    resolve y después create_playlist con la misma lista: sin esto se paga
    dos veces cada búsqueda. Solo se guarda lo encontrado."""
    clave = "res:" + norm(clave)
    hay, valor = cache.obtener(clave, DIAS_MEMO * 86400)
    if hay:
        return valor
    valor = fn()
    if valor:
        cache.guardar(clave, valor)
    return valor


def resolve_items(sp: SpotifyClient, tracks: list[str], albums: list[str]) -> dict:
    """Resuelve listas de 'Artista – Canción' y 'Artista – Álbum'.

    Devuelve {"resolved": [...], "unresolved": [...], "uris": [...],
    "total_minutes": n} conservando el orden dado (canciones primero, luego
    los álbumes completos).
    """
    resolved, unresolved, uris = [], [], []
    minutes = 0.0

    def do_track(item: str):
        try:
            artist, title = parse_item(item)
        except ValueError as e:
            return item, None, str(e)
        return item, _memo("t:" + item, lambda: find_track(sp, artist, title)), None

    def do_album(item: str):
        try:
            artist, album = parse_item(item)
        except ValueError as e:
            return item, None, str(e)
        def buscar():
            a = find_album(sp, artist, album)
            return album_details(sp, a["id"]) if a else None
        return item, _memo("a:" + item, buscar), None

    with ThreadPoolExecutor(max_workers=4) as pool:
        track_results = list(pool.map(do_track, tracks))
        album_results = list(pool.map(do_album, albums))

    for item, t, err in track_results:
        if t:
            s = _track_summary(t)
            resolved.append({"input": item, "type": "track", **s})
            uris.append(t["uri"])
            minutes += s["minutes"]
        else:
            unresolved.append({"input": item, "type": "track",
                               "reason": err or "no encontrada en Spotify"})
    for item, d, err in album_results:
        if d:
            fila = {"input": item, "type": "album", "album": d["album"],
                    "artist": d["artist"], "year": d["year"],
                    "n_tracks": d["n_tracks"], "minutes": d["minutes"]}
            if d["minutes"] > MINUTOS_SOSPECHOSOS:
                fila["aviso"] = (f"Dura {d['minutes']} min: puede ser una edición "
                                 "ampliada o un recopilatorio. Comprueba si es "
                                 "el disco original antes de crear la lista.")
            resolved.append(fila)
            uris.extend(d["uris"])
            minutes += d["minutes"]
        else:
            unresolved.append({"input": item, "type": "album",
                               "reason": err or "no encontrado en Spotify"})
    return {"resolved": resolved, "unresolved": unresolved, "uris": uris,
            "total_minutes": round(minutes)}


def resolve_ordered(sp: SpotifyClient, items: list[str]) -> dict:
    """Como resolve_items, pero respetando el orden en que se piden.

    Cada elemento es "Artista – Canción" o "album: Artista – Álbum". Sirve
    para mezclar discos completos con canciones sueltas sin que las canciones
    se vayan al principio (p. ej. meter tres temas de un disco que solo
    existe en una edición de dos horas).
    """
    def uno(item: str):
        texto = item.strip()
        es_album = texto.lower().startswith("album:") or texto.lower().startswith("álbum:")
        if es_album:
            texto = texto.split(":", 1)[1].strip()
        try:
            artista, titulo = parse_item(texto)
        except ValueError as e:
            return item, "album" if es_album else "track", None, str(e)
        if es_album:
            def buscar():
                a = find_album(sp, artista, titulo)
                return album_details(sp, a["id"]) if a else None
            return item, "album", _memo(f"a:{artista} – {titulo}", buscar), None
        return item, "track", _memo(f"t:{artista} – {titulo}",
                                    lambda: find_track(sp, artista, titulo)), None

    with ThreadPoolExecutor(max_workers=4) as pool:
        filas = list(pool.map(uno, items))

    resolved, unresolved, uris, minutes = [], [], [], 0.0
    for item, tipo, dato, err in filas:
        if not dato:
            unresolved.append({"input": item, "type": tipo,
                               "reason": err or "no encontrado en Spotify"})
            continue
        if tipo == "album":
            fila = {"input": item, "type": "album", "album": dato["album"],
                    "artist": dato["artist"], "year": dato["year"],
                    "n_tracks": dato["n_tracks"], "minutes": dato["minutes"]}
            if dato["minutes"] > MINUTOS_SOSPECHOSOS:
                fila["aviso"] = (f"Dura {dato['minutes']} min: puede ser una "
                                 "edición ampliada o un recopilatorio.")
            resolved.append(fila)
            uris.extend(dato["uris"])
            minutes += dato["minutes"]
        else:
            fila = _track_summary(dato)
            resolved.append({"input": item, "type": "track", **fila})
            uris.append(dato["uri"])
            minutes += fila["minutes"]
    return {"resolved": resolved, "unresolved": unresolved, "uris": uris,
            "total_minutes": round(minutes)}


def create_playlist(sp: SpotifyClient, name: str, description: str,
                    uris: list[str], public: bool = False) -> dict:
    pl = sp.create_playlist(name, description[:300], uris, public=public)
    return {"id": pl["id"], "name": pl.get("name"),
            "url": (pl.get("external_urls") or {}).get("spotify"),
            "n_tracks": len(uris)}
