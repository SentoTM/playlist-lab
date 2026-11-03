"""Cliente best-effort de stats.fm.

stats.fm NO tiene API pública oficial; esto usa su API interna
(api.stats.fm), que funciona sin autenticación para perfiles públicos.
Puede romperse si stats.fm cambia su API — todos los métodos devuelven
listas vacías en caso de fallo en vez de tumbar la app.

Validado contra la API real (sep. 2026): /users/{u} devuelve el perfil con
`privacySettings`; /users/{u}/top/{tracks,artists}?range=lifetime&limit=N
respeta límites altos (200) y trae ids de Spotify y géneros de los artistas.
`range` admite 'weeks' | 'months' | 'lifetime'.
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
        except (httpx.HTTPError, ValueError):
            return None

    def available(self) -> bool:
        return self.profile() is not None

    def profile(self) -> dict | None:
        """Perfil público del usuario (o None si no existe / no hay red)."""
        data = self._get(f"/users/{self.username}")
        return (data or {}).get("item") if data else None

    def privacy_warnings(self) -> list[str]:
        """Avisos si el perfil oculta lo que necesitan los motores."""
        prof = self.profile()
        if prof is None:
            return [f"stats.fm: no se encuentra el usuario '{self.username}' "
                    "(o no hay red)."]
        priv = prof.get("privacySettings") or {}
        out = []
        for key, label in (("topTracks", "top tracks"), ("topArtists", "top artists")):
            if priv.get(key) is False:
                out.append(f"stats.fm: tus {label} no son públicos; actívalos en "
                           "Settings → Privacy para que este motor funcione.")
        return out

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
        """Top artistas. Devuelve [{'name', 'streams', 'spotify_id', 'genres'}]."""
        data = self._get(f"/users/{self.username}/top/artists",
                         range=range_, limit=limit)
        if not data:
            return []
        out = []
        for item in data.get("items", []):
            artist = item.get("artist") or {}
            ext = artist.get("externalIds") or {}
            spotify_ids = ext.get("spotify") or []
            out.append({
                "name": artist.get("name", ""),
                "streams": item.get("streams") or 0,
                "spotify_id": spotify_ids[0] if spotify_ids else None,
                "genres": list(artist.get("genres") or []),
            })
        return [a for a in out if a["name"]]

    def top_artists_todos(self, range_: str = "lifetime", min_streams: int = 10,
                          pagina: int = 300, max_artistas: int = 3000) -> list[dict]:
        """TODOS los artistas del historial con al menos `min_streams` escuchas.

        Los tops normales se quedan en los 50-300 primeros, y para rastrear
        novedades hace falta la cola larga: el grupo que escuchó 15 veces
        también puede sacar disco. Se pagina con `offset` y se para cuando
        las escuchas bajan del mínimo (vienen ordenados de más a menos), la
        página viene corta o stats.fm repite la página (si un día ignora el
        offset, mejor parar que dar vueltas).
        """
        out: list[dict] = []
        vistos: set[str] = set()
        offset = 0
        while offset < max_artistas:
            data = self._get(f"/users/{self.username}/top/artists",
                             range=range_, limit=pagina, offset=offset)
            items = (data or {}).get("items") or []
            nuevos = 0
            for item in items:
                artist = item.get("artist") or {}
                nombre = artist.get("name") or ""
                streams = item.get("streams") or 0
                if not nombre or nombre in vistos:
                    continue
                vistos.add(nombre)
                nuevos += 1
                if streams < min_streams:
                    continue
                ext = artist.get("externalIds") or {}
                out.append({"name": nombre, "streams": streams,
                            "spotify_id": (ext.get("spotify") or [None])[0],
                            "genres": list(artist.get("genres") or [])})
            ultimo = (items[-1].get("streams") or 0) if items else 0
            if not items or nuevos == 0 or len(items) < pagina or ultimo < min_streams:
                break
            offset += len(items)
        return out
