"""Novedades de tu órbita: qué ha salido hace poco que pueda interesarte.

No es "las novedades del mundo" (eso lo da cualquier buscador), sino las que
caen cerca de lo que escuchas y que todavía no conoces: discos recientes de
tus artistas, de sus vecinos según Last.fm, y de las novedades destacadas de
Spotify filtradas por tus géneros. Devuelve datos; el criterio lo pone la IA.
"""
import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor

from .clients.lastfm import LastfmClient
from .clients.spotify import SpotifyClient
from .clients.statsfm import StatsfmClient
from .text import norm

log = logging.getLogger("playlist_lab.discovery")


def _album_row(a: dict, why: str) -> dict:
    return {
        "artist": (a.get("artists") or [{}])[0].get("name", ""),
        "album": a.get("name", ""),
        "date": a.get("release_date", ""),
        "type": a.get("album_type"),
        "n_tracks": a.get("total_tracks"),
        "why": why,
        "id": a.get("id"),
    }


def orbit_artists(sp: SpotifyClient, lf: LastfmClient | None,
                  depth: int = 8, per_artist: int = 5) -> tuple[list[str], list[str]]:
    """(tus artistas recientes, sus vecinos según Last.fm)."""
    mine, seen = [], set()
    for rng in ("short_term", "medium_term"):
        for a in sp.top_artists(rng, 25):
            if norm(a["name"]) not in seen:
                seen.add(norm(a["name"]))
                mine.append(a["name"])
    mine = mine[:depth * 2]

    neighbours: list[str] = []
    if lf:
        def sims(name: str) -> list[str]:
            return [s["name"] for s in lf.similar_artists(name, per_artist)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for batch in pool.map(sims, mine[:depth]):
                for n in batch:
                    if norm(n) not in seen:
                        seen.add(norm(n))
                        neighbours.append(n)
    return mine, neighbours


def new_releases(sp: SpotifyClient, lf: LastfmClient | None, sf: StatsfmClient | None,
                 known: dict[str, dict], months: int = 3,
                 include_known_artists: bool = True,
                 max_artists: int = 16, paso=None) -> dict:
    """Discos publicados en los últimos `months` meses dentro de tu órbita.

    Separa lo que es de artistas que ya escuchas ("de los tuyos") de lo que
    viene de vecinos que aún no conoces ("alrededor"), que es donde suele
    estar lo interesante.
    """
    def avisar(texto: str) -> None:
        if paso:
            paso(texto)

    peticiones_al_empezar = SpotifyClient.peticiones
    cutoff = (dt.date.today() - dt.timedelta(days=months * 31)).isoformat()
    avisar("buscando artistas vecinos en Last.fm")
    mine, neighbours = orbit_artists(sp, lf)
    warnings = []

    def recent_for(name: str) -> list[dict]:
        # sin `artist_name`: el endpoint ya devuelve lo más nuevo primero y
        # completar con búsqueda dispararía el número de llamadas (el puente
        # MCP corta al minuto).
        found = sp.search_artist(name, limit=1)
        if not found:
            return []
        albums = sp.artist_albums(found[0]["id"], limit=10)
        return [a for a in albums
                if (a.get("release_date") or "") >= cutoff
                and a.get("album_type") in ("album", "single")]

    targets = (mine[:max_artists // 2] if include_known_artists else []) + \
              neighbours[:max_artists]
    avisar(f"mirando los discos recientes de {len(targets)} artistas")
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(recent_for, targets))

    de_los_tuyos, alrededor, seen_albums = [], [], set()
    for name, albums in zip(targets, batches):
        es_mio = norm(name) in known
        for a in albums:
            if a.get("id") in seen_albums:
                continue
            seen_albums.add(a.get("id"))
            row = _album_row(a, f"nuevo de {name}" if es_mio
                             else f"{name}, cercano a lo que escuchas")
            (de_los_tuyos if es_mio else alrededor).append(row)

    avisar("revisando las novedades destacadas de Spotify")
    destacadas = []
    for a in sp.new_releases(50):
        if (a.get("release_date") or "") < cutoff or a.get("id") in seen_albums:
            continue
        artist = (a.get("artists") or [{}])[0].get("name", "")
        if norm(artist) in known:
            continue
        destacadas.append(_album_row(a, "novedad destacada en Spotify"))
    if not destacadas:
        warnings.append("Spotify no devolvió novedades destacadas "
                        "(endpoint cerrado a apps nuevas); se usa solo tu órbita.")

    for lst in (de_los_tuyos, alrededor, destacadas):
        lst.sort(key=lambda r: r["date"], reverse=True)

    return {
        "desde": cutoff,
        "peticiones_a_spotify": SpotifyClient.peticiones - peticiones_al_empezar,
        "de_los_tuyos": de_los_tuyos,
        "alrededor": alrededor,
        "destacadas_spotify": destacadas[:25],
        "warnings": warnings,
    }
