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
from .clients.musicbrainz import MusicbrainzClient
from .clients.spotify import SpotifyClient, SpotifyRateLimited
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
            try:
                return [s["name"] for s in lf.similar_artists(name, per_artist)]
            except Exception as e:  # noqa: BLE001
                log.warning("Similares de %s fallaron: %s", name, e)
                return []
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
                 max_artists: int = 16, paso=None,
                 mb: MusicbrainzClient | None = None) -> dict:
    """Novedades de su órbita. Con `mb` no gasta ni una petición de Spotify.

    MusicBrainz da la fecha de primera edición y no tiene cuota (solo una
    petición por segundo), así que para "¿ha sacado algo este artista?" es
    mejor fuente que Spotify. Spotify queda para el final: resolver y crear.
    """
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

    fallos: dict[str, int] = {}

    def recent_mb(name: str) -> list[dict]:
        """Vía MusicBrainz: gratis, secuencial (1 petición/segundo)."""
        try:
            return [{"artist": r["artist"], "name": r["album"],
                     "release_date": r["fecha"], "album_type": (r.get("tipo") or "").lower(),
                     "id": None}
                    for r in mb.recent_by_artist(name, cutoff)]
        except Exception as e:  # noqa: BLE001
            log.warning("MusicBrainz falló con %s: %s", name, e)
            fallos[type(e).__name__] = fallos.get(type(e).__name__, 0) + 1
            return []

    def recent_for(name: str) -> list[dict]:
        """Discos recientes de un artista.

        Un fallo suyo no tumba la tanda, pero SE CUENTA: tragarse los errores
        en silencio hacía que una limitación de cuota de Spotify se
        presentara como "no hay novedades", que es justo la conclusión
        equivocada.
        """
        try:
            from .library import find_artist
            encontrado, _ = find_artist(sp, name)
            if not encontrado:
                fallos["no está en Spotify"] = fallos.get("no está en Spotify", 0) + 1
                return []
            albums = sp.artist_albums(encontrado["id"], limit=10)
            return [a for a in albums
                    if (a.get("release_date") or "") >= cutoff
                    and a.get("album_type") in ("album", "single")]
        except SpotifyRateLimited:
            fallos["límite de cuota de Spotify"] = \
                fallos.get("límite de cuota de Spotify", 0) + 1
            return []
        except Exception as e:  # noqa: BLE001
            log.warning("Discos recientes de %s fallaron: %s", name, e)
            clave = type(e).__name__
            fallos[clave] = fallos.get(clave, 0) + 1
            return []

    targets = (mine[:max_artists // 2] if include_known_artists else []) + \
              neighbours[:max_artists]
    if mb:
        avisar(f"mirando en MusicBrainz los discos recientes de {len(targets)} "
               "artistas (sin gastar cuota de Spotify)")
        batches = [recent_mb(n) for n in targets]  # secuencial: 1 petición/s
    else:
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

    destacadas = []
    novedades_spotify = []
    if not mb:  # en modo gratuito ni se intenta: el endpoint está cerrado igual
        avisar("revisando las novedades destacadas de Spotify")
        try:
            novedades_spotify = sp.new_releases(50)
        except SpotifyRateLimited as e:
            warnings.append(str(e))
    for a in novedades_spotify:
        if (a.get("release_date") or "") < cutoff or a.get("id") in seen_albums:
            continue
        artist = (a.get("artists") or [{}])[0].get("name", "")
        if norm(artist) in known:
            continue
        destacadas.append(_album_row(a, "novedad destacada en Spotify"))
    if not destacadas and not mb:
        warnings.append("Spotify no devolvió novedades destacadas "
                        "(endpoint cerrado a apps nuevas); se usa solo tu órbita.")

    for lst in (de_los_tuyos, alrededor, destacadas):
        lst.sort(key=lambda r: r["date"], reverse=True)

    consultados = len(targets)
    fallidos = sum(fallos.values())
    if fallidos:
        detalle = ", ".join(f"{n} por {motivo}" for motivo, n in fallos.items())
        warnings.append(
            f"De {consultados} artistas consultados, {fallidos} no se pudieron "
            f"comprobar ({detalle}). Las listas de abajo están INCOMPLETAS: no "
            "concluyas que no hay novedades.")

    return {
        "desde": cutoff,
        "fuente": "MusicBrainz (sin cuota de Spotify)" if mb else "Spotify",
        "artistas_consultados": consultados,
        "artistas_no_comprobados": fallos or None,
        "peticiones_a_spotify": SpotifyClient.peticiones - peticiones_al_empezar,
        "de_los_tuyos": de_los_tuyos,
        "alrededor": alrededor,
        "destacadas_spotify": destacadas[:25],
        "warnings": warnings,
    }
