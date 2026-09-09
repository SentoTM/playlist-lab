"""Motor 'perfil': solo con la API de Spotify.

Idea: partir de tus artistas y canciones top y expandir por sus
discografías y top tracks. El parámetro `novelty` (0..1) controla el
equilibrio entre lo que ya escuchas (0) y descubrimiento dentro de tu
órbita de artistas (1).
"""
from ..clients.spotify import SpotifyClient
from .core import Candidate, from_spotify_track, track_key


def known_track_keys(sp: SpotifyClient) -> set[str]:
    """Canciones que ya conoces bien (tops de varios rangos + recientes)."""
    keys: set[str] = set()
    for rng in ("short_term", "medium_term", "long_term"):
        for t in sp.top_tracks(rng, 50):
            a = t["artists"][0]["name"] if t.get("artists") else ""
            keys.add(track_key(a, t.get("name", "")))
    for t in sp.recently_played(50):
        a = t["artists"][0]["name"] if t.get("artists") else ""
        keys.add(track_key(a, t.get("name", "")))
    return keys


def generate(sp: SpotifyClient, novelty: float = 0.5,
             max_artists: int = 15) -> list[Candidate]:
    candidates: list[Candidate] = []
    known = known_track_keys(sp)

    # 1) Tus propios tops, con más peso cuanto menor sea novelty
    familiar_weight = 1.0 - novelty
    if familiar_weight > 0.05:
        for rng, w in (("short_term", 1.0), ("medium_term", 0.8), ("long_term", 0.6)):
            for rank, t in enumerate(sp.top_tracks(rng, 50)):
                score = familiar_weight * w * (1.0 - rank / 60)
                candidates.append(from_spotify_track(
                    t, score, "profile", f"en tu top ({rng.replace('_term', '')})"))

    # 2) Expansión: top tracks de tus artistas favoritos que NO conoces aún
    artists = sp.top_artists("medium_term", max_artists)
    artists += [a for a in sp.top_artists("long_term", max_artists)
                if a["id"] not in {x["id"] for x in artists}][: max_artists // 2]

    for rank, artist in enumerate(artists):
        artist_w = 1.0 - rank / (len(artists) + 5)
        for t in sp.artist_top_tracks(artist["id"], artist_name=artist["name"]):
            a = t["artists"][0]["name"] if t.get("artists") else ""
            is_known = track_key(a, t.get("name", "")) in known
            if is_known:
                continue  # lo conocido ya entra por el bloque 1
            score = novelty * artist_w * (t.get("popularity", 50) / 100)
            candidates.append(from_spotify_track(
                t, score, "profile",
                f"de {artist['name']}, uno de tus artistas top"))

    # 3) Con novelty alta, rasca también en álbumes recientes de tus artistas
    if novelty > 0.6:
        for artist in artists[:8]:
            for album in sp.artist_albums(artist["id"], limit=3):
                for t in sp.album_tracks(album["id"], limit=50)[:4]:
                    a = t["artists"][0]["name"] if t.get("artists") else artist["name"]
                    if track_key(a, t.get("name", "")) in known:
                        continue
                    t.setdefault("album", album)  # album_tracks no trae album
                    candidates.append(from_spotify_track(
                        t, novelty * 0.4, "profile",
                        f"del álbum «{album.get('name', '')}» de {artist['name']}"))

    return candidates
