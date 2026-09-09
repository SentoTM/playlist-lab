"""Búsqueda, resolución y creación en Spotify.

La IA propone en texto ("Artista – Canción", "Artista – Álbum"); aquí se
convierte eso en URIs verificadas y se crea la playlist. Siempre se informa
de lo que no se ha podido resolver para que se corrija en conversación.
"""
from concurrent.futures import ThreadPoolExecutor

from .clients.spotify import SpotifyClient
from .text import norm, parse_item


def _artist_matches(candidate: dict, artist: str) -> bool:
    names = [a.get("name", "") for a in candidate.get("artists", [])]
    return any(norm(n) == norm(artist) for n in names) or any(
        norm(artist) in norm(n) or norm(n) in norm(artist) for n in names)


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


def find_album(sp: SpotifyClient, artist: str, album: str) -> dict | None:
    results = sp.search_album(f'album:"{album}" artist:"{artist}"', limit=5) \
        or sp.search_album(f"{album} {artist}", limit=5)
    good = [a for a in results if _artist_matches(a, artist)]
    if not good:
        return None
    # preferir álbum sobre single/compilación, y título más parecido
    good.sort(key=lambda a: (a.get("album_type") != "album",
                             norm(a.get("name", "")) != norm(album)))
    return good[0]


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
        return item, find_track(sp, artist, title), None

    def do_album(item: str):
        try:
            artist, album = parse_item(item)
        except ValueError as e:
            return item, None, str(e)
        a = find_album(sp, artist, album)
        return item, (album_details(sp, a["id"]) if a else None), None

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
            resolved.append({"input": item, "type": "album", "album": d["album"],
                             "artist": d["artist"], "year": d["year"],
                             "n_tracks": d["n_tracks"], "minutes": d["minutes"]})
            uris.extend(d["uris"])
            minutes += d["minutes"]
        else:
            unresolved.append({"input": item, "type": "album",
                               "reason": err or "no encontrado en Spotify"})
    return {"resolved": resolved, "unresolved": unresolved, "uris": uris,
            "total_minutes": round(minutes)}


def create_playlist(sp: SpotifyClient, name: str, description: str,
                    uris: list[str], public: bool = False) -> dict:
    pl = sp.create_playlist(name, description[:300], uris, public=public)
    return {"id": pl["id"], "name": pl.get("name"),
            "url": (pl.get("external_urls") or {}).get("spotify"),
            "n_tracks": len(uris)}
