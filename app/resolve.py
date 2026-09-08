"""Resolución de candidatos a URIs de Spotify (para motores que devuelven
solo nombre+artista, como Last.fm)."""
from concurrent.futures import ThreadPoolExecutor

from .clients.spotify import SpotifyClient
from .engines.core import Candidate


def resolve_on_spotify(sp: SpotifyClient, candidates: list[Candidate]) -> list[Candidate]:
    def resolve(c: Candidate) -> Candidate | None:
        if c.spotify_uri:
            return c
        results = sp.search_track(f"track:{c.name} artist:{c.artist}", limit=1) \
            or sp.search_track(f"{c.name} {c.artist}", limit=1)
        if not results:
            return None
        t = results[0]
        c.spotify_id, c.spotify_uri = t.get("id"), t.get("uri")
        images = (t.get("album") or {}).get("images") or []
        c.album_image = images[-1]["url"] if images else None
        return c

    with ThreadPoolExecutor(max_workers=4) as pool:
        resolved = list(pool.map(resolve, candidates))
    return [c for c in resolved if c]
