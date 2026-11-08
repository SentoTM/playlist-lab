"""Homónimos en resolve: 'Embrace (Washington) – Embrace'.

Spotify no permite distinguir a dos grupos que se llaman igual, y MusicBrainz
sí: la pista elige al artista exacto allí y su ficha enlaza con el de Spotify.
Lo encontrado se convierte en una URI y sigue el camino normal de resolve.

Si se ha pedido un artista concreto y no se puede garantizar, la pieza queda
sin resolver: es mejor un hueco visible que el disco de otro grupo.
"""
from . import cache, conexiones, library
from .clients.spotify import SpotifyClient
from .text import norm, parse_item

MEMO_DIAS = 30
_PREFIJOS = ("album:", "álbum:")


def _buscar_disco(sp: SpotifyClient, artista_id: str, nombre: str, titulo: str) -> dict | None:
    buscado = library._plano(norm(titulo))
    discos = [a for a in sp.artist_albums(artista_id, limit=100, artist_name=nombre,
                                            max_paginas=10)
              if library._plano(norm(a.get("name", ""))) == buscado]
    return library.mejor_album(discos, titulo) if discos else None


def _disco_por_anio(sp: SpotifyClient, ficha: dict, titulo: str, mb) -> dict | None:
    """Sin enlace a Spotify, el año de MusicBrainz separa a los homónimos.

    Solo vale si todos los discos de ese año son de un único artista: con
    dos candidatos posibles no se puede garantizar cuál es.
    """
    anio = (mb.fecha_disco(ficha["mbid"], titulo) or "")[:4]
    if not anio:
        return None
    nombre, buscado = library._plano(ficha["artist"]), library._plano(norm(titulo))
    discos, artistas = [], set()
    for a in library._candidatos_album(sp, ficha["artist"], titulo):
        suyos = [x.get("id") for x in a.get("artists", [])
                 if library._plano(x.get("name", "")) == nombre]
        if (suyos and library._plano(norm(a.get("name", ""))) == buscado
                and (a.get("release_date") or "")[:4] == anio):
            discos.append(a)
            artistas.update(suyos)
    return library.mejor_album(discos, titulo) if len(artistas) == 1 else None


def _buscar_cancion(sp: SpotifyClient, artista_id: str, nombre: str, titulo: str) -> dict | None:
    buscado = library._plano(norm(titulo))
    for t in sp.search_track(f'track:"{titulo}" artist:"{nombre}"', limit=10):
        if (any(a.get("id") == artista_id for a in t.get("artists", []))
                and library._plano(norm(t.get("name", ""))) == buscado):
            return t
    return None


def _traducir(sp, item: str, tipo_lista: str, mb) -> tuple[str, str | None]:
    """(item a resolver, motivo si no se puede garantizar el artista)."""
    if library.separar_uri(item)[1]:
        return item, None
    texto = item.strip()
    es_disco = texto.lower().startswith(_PREFIJOS)
    if es_disco:
        texto = texto.split(":", 1)[1].strip()
    try:
        artista, titulo = parse_item(texto)
    except ValueError:
        return item, None
    if not conexiones._PISTA.match(artista):
        return item, None
    memo = f"homonimo:{norm(item)}"
    hay, valor = cache.obtener(memo, MEMO_DIAS * 86400)
    if hay:
        return valor, None
    identificado = conexiones.identificar(artista, mb)
    # Sin coincidencia, el paréntesis puede ser parte del nombre real.
    if identificado.get("error") or identificado["avisos"]:
        return item, None

    ficha = identificado["ficha"]
    datos = mb.relaciones(ficha["mbid"])
    enlace = conexiones.spotify_de(datos or {})
    es_album = es_disco or tipo_lista == "album"
    tipo = "album" if es_album else "track"
    if enlace:
        artista_id = enlace.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        buscar = _buscar_disco if es_album else _buscar_cancion
        encontrado = buscar(sp, artista_id, ficha["artist"], titulo)
    else:
        encontrado = _disco_por_anio(sp, ficha, titulo, mb) if es_album else None
        if not encontrado:
            return item, (f"MusicBrainz identifica a {ficha['artist']}, pero sin enlace a "
                          "Spotify no se puede asegurar cuál es: pasa la URI")
    if not encontrado:
        return item, f"{ficha['artist']} no tiene '{titulo}' en Spotify"
    nuevo = f"{ficha['artist']} – {titulo} | spotify:{tipo}:{encontrado['id']}"
    cache.guardar(memo, nuevo)
    return nuevo, None


def preparar(sp, lista: list[str], tipo_lista: str, mb) -> tuple[list[str], dict, list[dict]]:
    """(lista traducida, {traducido: original}, sin resolver)."""
    salida, originales, fuera = [], {}, []
    for item in lista:
        nuevo, motivo = _traducir(sp, item, tipo_lista, mb)
        if motivo:
            es_disco = tipo_lista == "album" or item.strip().lower().startswith(_PREFIJOS)
            fuera.append({"input": item, "type": "album" if es_disco else "track",
                          "reason": motivo})
            continue
        salida.append(nuevo)
        if nuevo != item:
            originales[nuevo] = item
    return salida, originales, fuera
