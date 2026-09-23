"""Cliente de la Spotify Web API con OAuth 2.0 + PKCE (sin client secret).

El token se guarda en token.json junto al proyecto para no tener que
volver a hacer login en cada arranque.
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

import httpx

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

SCOPES = " ".join([
    "user-top-read",
    "user-library-read",
    "user-read-recently-played",
    "user-follow-read",
    "user-read-currently-playing",
    "playlist-modify-private",
    "playlist-modify-public",
    "playlist-read-private",
])

TOKEN_FILE = Path(__file__).resolve().parents[2] / "token.json"
log = logging.getLogger("playlist_lab.spotify")
MAX_ESPERA_429 = 10  # segundos; por encima, mejor avisar que quedarse colgado


class SpotifyRateLimited(RuntimeError):
    """Spotify pide una espera demasiado larga para aguantarla en caliente."""


class SpotifyAuthError(Exception):
    pass


class _RateLimiter:
    """Freno compartido: Spotify en modo desarrollo tiene cuota por
    desarrollador y responde 429 si vamos en tromba. Más vale ir a ritmo fijo
    que dormir esperas largas después."""

    def __init__(self, por_segundo: float = 8.0):
        self._intervalo = 1.0 / por_segundo
        self._lock = threading.Lock()
        self._siguiente = 0.0

    def esperar(self) -> None:
        with self._lock:
            ahora = time.monotonic()
            if self._siguiente > ahora:
                time.sleep(self._siguiente - ahora)
                ahora = time.monotonic()
            self._siguiente = ahora + self._intervalo


class SpotifyClient:
    # compartidos por todas las instancias: la cuota de Spotify es por app
    _limiter = _RateLimiter(8.0)
    peticiones = 0     # contador para saber cuánto cuesta cada operación
    limitaciones = 0   # cuántas veces nos han frenado con un 429
    bloqueado_hasta = 0.0  # marca de tiempo hasta la que Spotify nos frena

    def __init__(self, client_id: str, redirect_uri: str):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self._verifier: str | None = None
        self._token: dict | None = self._load_token()
        self._http = httpx.Client(timeout=20)

    # ---------- OAuth PKCE ----------

    def auth_url(self) -> str:
        self._verifier = secrets.token_urlsafe(64)[:128]
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self._verifier.encode()).digest()
        ).rstrip(b"=").decode()
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        return f"{AUTH_URL}?{httpx.QueryParams(params)}"

    def exchange_code(self, code: str) -> None:
        if not self._verifier:
            raise SpotifyAuthError("No hay code_verifier: inicia el login desde /login")
        resp = self._http.post(TOKEN_URL, data={
            "client_id": self.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": self._verifier,
        })
        resp.raise_for_status()
        self._store_token(resp.json())

    def _refresh(self) -> None:
        if not self._token or "refresh_token" not in self._token:
            raise SpotifyAuthError("Sesión no iniciada")
        resp = self._http.post(TOKEN_URL, data={
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": self._token["refresh_token"],
        })
        if resp.status_code != 200:
            TOKEN_FILE.unlink(missing_ok=True)
            self._token = None
            raise SpotifyAuthError("El refresh token ha caducado, vuelve a hacer login")
        data = resp.json()
        data.setdefault("refresh_token", self._token["refresh_token"])
        self._store_token(data)

    def _store_token(self, data: dict) -> None:
        data["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
        self._token = data
        TOKEN_FILE.write_text(json.dumps(data))
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass

    @staticmethod
    def _load_token() -> dict | None:
        if TOKEN_FILE.exists():
            try:
                return json.loads(TOKEN_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                return None
        return None

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    def missing_scopes(self) -> list[str]:
        """Permisos que pide la app pero no tiene el token guardado.

        Pasa cuando se añaden permisos nuevos: el token viejo sigue siendo
        válido pero le faltan, y las llamadas fallan con 401/403. Se arregla
        cerrando sesión y volviendo a entrar en la web."""
        if not self._token:
            return []
        tiene = set((self._token.get("scope") or "").split())
        return [s for s in SCOPES.split() if s not in tiene]

    def logout(self) -> None:
        TOKEN_FILE.unlink(missing_ok=True)
        self._token = None

    # ---------- HTTP con token ----------

    @classmethod
    def segundos_bloqueado(cls) -> int:
        """Cuánto queda del castigo de Spotify (0 si no hay)."""
        return max(0, round(cls.bloqueado_hasta - time.time()))

    def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self._token:
            raise SpotifyAuthError("Sesión no iniciada")
        restante = self.segundos_bloqueado()
        if restante:
            # no gastar más cuota mientras dura el castigo: solo lo alarga
            raise SpotifyRateLimited(
                f"Spotify sigue limitando la app: quedan {restante} s "
                f"({restante // 60} min). No se lanzan más peticiones hasta "
                "entonces.")
        if time.time() >= self._token.get("expires_at", 0):
            self._refresh()
        for attempt in range(3):
            self._limiter.esperar()
            type(self).peticiones += 1
            resp = self._http.request(
                method, f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {self._token['access_token']}"},
                **kwargs,
            )
            if resp.status_code == 429:
                espera = int(resp.headers.get("Retry-After", "2"))
                type(self).limitaciones += 1
                type(self).bloqueado_hasta = time.time() + espera
                log.warning("Spotify 429 en %s: pide esperar %ss", path, espera)
                if espera > MAX_ESPERA_429:
                    raise SpotifyRateLimited(
                        f"Spotify ha limitado la app y pide esperar {espera} s "
                        f"({espera // 60} min). Es la cuota del modo desarrollo, "
                        "que se comparte entre todas tus consultas: no insistas, "
                        "espera y evita mientras tanto las consultas grandes.")
                time.sleep(espera + 1)
                continue
            if resp.status_code == 401 and attempt == 0:
                self._refresh()
                continue
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        resp.raise_for_status()
        return {}

    def _get(self, path: str, **params) -> dict:
        """GET que degrada con gracia: un 400/404 (p. ej. artistas raros en
        /artists/{id}/albums) devuelve {} y deja un aviso en el log, en vez de
        tumbar toda la generación. Los errores de auth (401/403) sí se propagan."""
        try:
            return self._request("GET", path,
                                 params={k: v for k, v in params.items() if v is not None})
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 404):
                log.warning("Spotify %s en %s (%s): se ignora",
                            e.response.status_code, path, e.response.text[:120])
                return {}
            raise

    # ---------- Endpoints ----------

    def me(self) -> dict:
        return self._get("/me")

    def top_tracks(self, time_range: str = "medium_term", limit: int = 50) -> list[dict]:
        return self._get("/me/top/tracks", time_range=time_range, limit=limit).get("items", [])

    def top_artists(self, time_range: str = "medium_term", limit: int = 50) -> list[dict]:
        return self._get("/me/top/artists", time_range=time_range, limit=limit).get("items", [])

    def recently_played(self, limit: int = 50) -> list[dict]:
        items = self._get("/me/player/recently-played", limit=limit).get("items", [])
        return [i["track"] for i in items if i.get("track")]

    def saved_tracks(self, limit: int = 50, offset: int = 0) -> list[dict]:
        items = self._get("/me/tracks", limit=limit, offset=offset).get("items", [])
        return [i["track"] for i in items if i.get("track")]

    def all_saved_tracks(self, max_items: int = 600) -> list[dict]:
        """Toda tu biblioteca de canciones guardadas (paginando)."""
        out = []
        for offset in range(0, max_items, 50):
            batch = self.saved_tracks(50, offset)
            out.extend(batch)
            if len(batch) < 50:
                break
        return out

    def saved_albums(self, max_items: int = 300) -> list[dict]:
        """Álbumes guardados, con la fecha en que los guardaste."""
        out = []
        for offset in range(0, max_items, 50):
            items = self._get("/me/albums", limit=50, offset=offset).get("items", [])
            for i in items:
                a = i.get("album") or {}
                if a:
                    a["_added_at"] = i.get("added_at", "")
                    out.append(a)
            if len(items) < 50:
                break
        return out

    def my_playlists(self, max_items: int = 200) -> list[dict]:
        """Tus playlists (incluidas las que sigues)."""
        out = []
        for offset in range(0, max_items, 50):
            items = self._get("/me/playlists", limit=50, offset=offset).get("items", [])
            out.extend([i for i in items if i])
            if len(items) < 50:
                break
        return out

    def playlist_tracks(self, playlist_id: str, max_items: int = 200) -> list[dict]:
        out = []
        for offset in range(0, max_items, 100):
            items = self._get(f"/playlists/{playlist_id}/items",
                              limit=100, offset=offset).get("items", [])
            out.extend([i["track"] for i in items if i.get("track")])
            if len(items) < 100:
                break
        return out

    def followed_artists(self, max_items: int = 300) -> list[dict]:
        """Artistas que sigues. Requiere el permiso user-follow-read: si el
        token es anterior a añadirlo, devuelve [] en vez de fallar."""
        out, after = [], None
        try:
            while len(out) < max_items:
                params = {"type": "artist", "limit": 50}
                if after:
                    params["after"] = after
                data = self._request("GET", "/me/following", params=params
                                     ).get("artists", {})
                items = data.get("items", [])
                out.extend(items)
                after = (data.get("cursors") or {}).get("after")
                if not after or not items:
                    break
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                log.warning("Sin permiso user-follow-read: vuelve a hacer login")
                return []
            raise
        return out

    def currently_playing(self) -> dict | None:
        """Qué suena ahora mismo (o None). Requiere user-read-currently-playing."""
        try:
            data = self._request("GET", "/me/player/currently-playing")
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403, 404):
                return None
            raise
        return (data or {}).get("item")

    _top_tracks_forbidden = False  # Spotify devuelve 403 a las apps nuevas (2026)

    def artist_top_tracks(self, artist_id: str, market: str = "from_token",
                          artist_name: str | None = None) -> list[dict]:
        """Temas populares de un artista.

        El endpoint oficial /artists/{id}/top-tracks está prohibido (403) para
        apps nuevas en modo desarrollo; si falla, se aproxima buscando
        `artist:"Nombre"` (la búsqueda ordena por popularidad) y filtrando por
        id de artista para evitar homónimos.
        """
        if not self._top_tracks_forbidden:
            try:
                return self._request("GET", f"/artists/{artist_id}/top-tracks",
                                     params={"market": market}).get("tracks", [])
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 403:
                    raise
                SpotifyClient._top_tracks_forbidden = True
                log.warning("Spotify prohíbe /top-tracks a esta app; se usa búsqueda")
        if not artist_name:
            artist_name = self._get(f"/artists/{artist_id}").get("name")
            if not artist_name:
                return []
        found = self.search_track(f'artist:"{artist_name}"', limit=20)
        same = [t for t in found
                if any(a.get("id") == artist_id for a in t.get("artists", []))]
        same.sort(key=lambda t: t.get("popularity", 0), reverse=True)
        return same[:10]

    def artist_albums(self, artist_id: str, limit: int = 20,
                      artist_name: str | None = None,
                      max_paginas: int = 4) -> list[dict]:
        """Discografía en Spotify, de lo más nuevo a lo más viejo.

        Tres recortes de la API que hay que sortear (verificado en sep. 2026
        con scripts/diag_spotify.py):
        1) `limit` solo admite 0-10 (antes 50): pasarse da 400.
        2) Al devolver 10 por página y NO garantizar orden por fecha, pedir
           una sola página puede traer los discos más antiguos y hacer creer
           que el artista lleva años sin publicar. Por eso se pagina con
           `offset` y se ordena aquí por fecha descendente.
        3) Si aun así no hay nada, se completa con search(artist:"Nombre"),
           filtrando por id para evitar homónimos.
        """
        items: list[dict] = []
        for pagina in range(max_paginas):
            page = self._get(f"/artists/{artist_id}/albums",
                             include_groups="album,single",
                             limit=self.MAX_PAGE,
                             offset=pagina * self.MAX_PAGE).get("items", [])
            items.extend(page)
            if len(page) < self.MAX_PAGE:
                break
        if not items and artist_name:
            items = [a for a in self.search_album(f'artist:"{artist_name}"', 20)
                     if any(x.get("id") == artist_id for x in a.get("artists", []))]
        vistos, unicos = set(), []
        for a in items:
            if a.get("id") and a["id"] not in vistos:
                vistos.add(a["id"])
                unicos.append(a)
        unicos.sort(key=lambda a: a.get("release_date") or "", reverse=True)
        return unicos[:limit]

    def new_releases(self, limit: int = 50, country: str | None = None) -> list[dict]:
        """Novedades destacadas de Spotify. Puede estar cerrado (403) a apps
        nuevas: en ese caso se devuelve [] y se tira de otras vías."""
        try:
            return self._request("GET", "/browse/new-releases",
                                 params={"limit": limit, **({"country": country} if country else {})}
                                 ).get("albums", {}).get("items", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 403, 404):
                log.warning("Spotify %s en /browse/new-releases: se ignora",
                            e.response.status_code)
                return []
            raise

    def album_tracks(self, album_id: str, limit: int = 50) -> list[dict]:
        return self._get(f"/albums/{album_id}/tracks", limit=limit).get("items", [])

    # Spotify bajó el tope de `limit` a 10 en /search y en /artists/{id}/albums
    # (sep. 2026). Pasarse devuelve 400 "Invalid limit", así que se pagina.
    MAX_PAGE = 10

    def _search_paged(self, query: str, kind: str, want: int) -> list[dict]:
        """Busca `want` resultados paginando de 10 en 10 (tope de la API)."""
        clave = {"track": "tracks", "album": "albums", "artist": "artists"}[kind]
        out: list[dict] = []
        for offset in range(0, min(want, 1000), self.MAX_PAGE):
            page = self._get("/search", q=query, type=kind,
                             limit=min(self.MAX_PAGE, want - len(out)),
                             offset=offset).get(clave, {}).get("items", [])
            out.extend(page)
            if len(page) < self.MAX_PAGE or len(out) >= want:
                break
        return out[:want]

    def search_track(self, query: str, limit: int = 3) -> list[dict]:
        return self._search_paged(query, "track", limit)

    def album(self, album_id: str) -> dict:
        """Álbum completo, con tracks (incluye duration_ms por pista)."""
        return self._get(f"/albums/{album_id}", market="from_token")

    def search_album(self, query: str, limit: int = 3) -> list[dict]:
        return self._search_paged(query, "album", limit)

    def search_albums_filtered(self, text: str = "", year: str = "",
                               hipster: bool = False, new: bool = False,
                               limit: int = 50, offset: int = 0) -> list[dict]:
        """Búsqueda de álbumes con los filtros de Spotify que aún funcionan.

        OJO: `genre:` ya no filtra en búsqueda de álbumes para apps nuevas
        (sep. 2026), y `tag:new`/`tag:hipster` con texto libre devuelven sobre
        todo ruido. Para descubrir por género usa explore.emerging, que se
        apoya en las etiquetas de Last.fm. Esto queda para el filtro `year:`,
        que sí es fiable.
        """
        parts = []
        if text:
            parts.append(text)
        if year:
            parts.append(f"year:{year}")
        if hipster:
            parts.append("tag:hipster")
        if new:
            parts.append("tag:new")
        if not parts:
            return []
        return self._search_paged(" ".join(parts), "album", limit)

    def artists_by_id(self, ids: list[str]) -> list[dict]:
        """Varios artistas de una vez.

        OJO: `/artists` devuelve 403 a las apps nuevas (sep. 2026), así que
        en la práctica esto suele volver vacío. No hay forma de leer
        `popularity` ni `followers`: para medir el tamaño de un artista usa
        los oyentes de Last.fm (lf.artist_info).
        """
        out = []
        for i in range(0, len(ids), 50):
            chunk = [x for x in ids[i:i + 50] if x]
            if not chunk:
                continue
            try:
                out.extend(self._request(
                    "GET", "/artists", params={"ids": ",".join(chunk)}
                ).get("artists", []))
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (400, 403, 404):
                    log.warning("Spotify %s en /artists: sin popularidad",
                                e.response.status_code)
                    return out
                raise
        return out

    def search_artist(self, query: str, limit: int = 3) -> list[dict]:
        return self._search_paged(query, "artist", limit)

    def create_playlist(self, name: str, description: str, uris: list[str],
                        public: bool = False) -> dict:
        """Crea la playlist y la llena, en tandas de 100 (tope de la API).

        Rutas actuales (sep. 2026): POST /me/playlists para crearla y
        POST /playlists/{id}/items para llenarla. Las antiguas
        (/users/{id}/playlists y /playlists/{id}/tracks) están deprecadas y
        a las apps nuevas les devuelven 403.
        """
        playlist = self._request(
            "POST", "/me/playlists",
            json={"name": name, "description": description, "public": public},
        )
        for i in range(0, len(uris), 100):
            self._request(
                "POST", f"/playlists/{playlist['id']}/items",
                json={"uris": uris[i:i + 100]},
            )
        return playlist
