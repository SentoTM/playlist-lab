"""Cliente mínimo de la API de Last.fm (solo lectura, API key gratuita)."""
import httpx

API = "https://ws.audioscrobbler.com/2.0/"


class LastfmClient:
    def __init__(self, api_key: str, username: str | None = None):
        self.api_key = api_key
        self.username = username
        self._http = httpx.Client(timeout=20)

    def _get(self, method: str, **params) -> dict:
        resp = self._http.get(API, params={
            "method": method, "api_key": self.api_key, "format": "json", **params,
        })
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Last.fm error {data['error']}: {data.get('message')}")
        return data

    def similar_tracks(self, artist: str, track: str, limit: int = 20) -> list[dict]:
        """Devuelve [{'name', 'artist', 'match'}] de canciones similares."""
        try:
            data = self._get("track.getSimilar", artist=artist, track=track,
                             limit=limit, autocorrect=1)
        except (httpx.HTTPError, RuntimeError):
            return []
        items = data.get("similartracks", {}).get("track", [])
        return [{
            "name": t.get("name", ""),
            "artist": t.get("artist", {}).get("name", ""),
            "match": float(t.get("match", 0)),
        } for t in items if t.get("name")]

    def similar_artists(self, artist: str, limit: int = 15) -> list[dict]:
        try:
            data = self._get("artist.getSimilar", artist=artist, limit=limit, autocorrect=1)
        except (httpx.HTTPError, RuntimeError):
            return []
        items = data.get("similarartists", {}).get("artist", [])
        return [{"name": a.get("name", ""), "match": float(a.get("match", 0))}
                for a in items if a.get("name")]

    def user_top_tracks(self, period: str = "overall", limit: int = 50) -> list[dict]:
        """Top del usuario en Last.fm — incluye scrobbles de fuera de Spotify."""
        if not self.username:
            return []
        try:
            data = self._get("user.getTopTracks", user=self.username,
                             period=period, limit=limit)
        except (httpx.HTTPError, RuntimeError):
            return []
        items = data.get("toptracks", {}).get("track", [])
        return [{
            "name": t.get("name", ""),
            "artist": t.get("artist", {}).get("name", ""),
            "playcount": int(t.get("playcount", 0)),
        } for t in items if t.get("name")]

    def tag_top_albums(self, tag: str, limit: int = 50, page: int = 1) -> list[dict]:
        """Álbumes más escuchados globalmente para un tag/género."""
        try:
            data = self._get("tag.getTopAlbums", tag=tag, limit=limit, page=page)
        except (httpx.HTTPError, RuntimeError):
            return []
        items = data.get("albums", {}).get("album", [])
        return [{"name": a.get("name", ""),
                 "artist": a.get("artist", {}).get("name", "")}
                for a in items if a.get("name")]

    def artist_top_albums(self, artist: str, limit: int = 10) -> list[dict]:
        try:
            data = self._get("artist.getTopAlbums", artist=artist,
                             limit=limit, autocorrect=1)
        except (httpx.HTTPError, RuntimeError):
            return []
        items = data.get("topalbums", {}).get("album", [])
        return [{"name": a.get("name", ""),
                 "artist": a.get("artist", {}).get("name", "")}
                for a in items if a.get("name")]

    def user_artist_playcount(self, artist: str) -> int:
        """Cuántas veces ha escuchado el usuario a un artista (0 si nunca)."""
        if not self.username:
            return 0
        try:
            data = self._get("artist.getInfo", artist=artist,
                             username=self.username, autocorrect=1)
        except (httpx.HTTPError, RuntimeError):
            return 0
        return int(data.get("artist", {}).get("stats", {}).get("userplaycount", 0) or 0)

    def user_top_artists(self, period: str = "overall", limit: int = 30) -> list[dict]:
        if not self.username:
            return []
        try:
            data = self._get("user.getTopArtists", user=self.username,
                             period=period, limit=limit)
        except (httpx.HTTPError, RuntimeError):
            return []
        items = data.get("topartists", {}).get("artist", [])
        return [{"name": a.get("name", ""), "playcount": int(a.get("playcount", 0))}
                for a in items if a.get("name")]
