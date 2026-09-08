"""Cliente best-effort de stats.fm.

stats.fm NO tiene API pública oficial; esto usa su API interna
(api.stats.fm), que funciona sin autenticación para perfiles públicos.
Puede romperse si stats.fm cambia su API — todos los métodos devuelven
listas vacías en caso de fallo en vez de tumbar la app.
"""
import httpx

API = "https://api.stats.fm/api/v1"
HEADERS = {"User-Agent": "playlist-lab/0.1 (uso personal)"}


class StatsfmClient:
    def __init__(self, username: str):
        self.username = username
        self._http = httpx.Client(timeout=20, headers=HEADERS)

    def _get(self, path: str, **params) -> dict | None:
        try:
            resp = self._http.get(f"{API}{path}", params=params)
            if resp.status_code != 200:
                return None
            return resp.json()
        except httpx.HTTPError:
            return None

    def available(self) -> bool:
        return self._get(f"/users/{self.username}") is not None

    def top_tracks(self, range_: str = "lifetime", limit: int = 100) -> list[dict]:
        """Top tracks del historial ('weeks' | 'months' | 'lifetime').

        Devuelve [{'name', 'artist', 'spotify_id', 'streams'}].
        """
        data = self._get(f"/users/{self.username}/top/tracks",
                         range=range_, limit=limit)
        if not data:
            return []
        out = []
        for item in data.get("items", []):
            track = item.get("track") or {}
            artists = track.get("artists") or []
            ext = track.get("externalIds") or {}
            spotify_ids = ext.get("spotify") or []
            out.append({
                "name": track.get("name", ""),
                "artist": artists[0].get("name", "") if artists else "",
                "spotify_id": spotify_ids[0] if spotify_ids else None,
                "streams": item.get("streams") or 0,
            })
        return [t for t in out if t["name"]]

    def top_artists(self, range_: str = "lifetime", limit: int = 50) -> list[dict]:
        data = self._get(f"/users/{self.username}/top/artists",
                         range=range_, limit=limit)
        if not data:
            return []
        out = []
        for item in data.get("items", []):
            artist = item.get("artist") or {}
            out.append({
                "name": artist.get("name", ""),
                "streams": item.get("streams") or 0,
            })
        return [a for a in out if a["name"]]
