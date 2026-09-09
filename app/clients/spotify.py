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
    "playlist-modify-private",
    "playlist-modify-public",
    "playlist-read-private",
])

TOKEN_FILE = Path(__file__).resolve().parents[2] / "token.json"
log = logging.getLogger("playlist_lab.spotify")


class SpotifyAuthError(Exception):
    pass


class SpotifyClient:
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

    def logout(self) -> None:
        TOKEN_FILE.unlink(missing_ok=True)
        self._token = None

    # ---------- HTTP con token ----------

    def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self._token:
            raise SpotifyAuthError("Sesión no iniciada")
        if time.time() >= self._token.get("expires_at", 0):
            self._refresh()
        for attempt in range(3):
            resp = self._http.request(
                method, f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {self._token['access_token']}"},
                **kwargs,
            )
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", "2")) + 1)
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
                      market: str = "from_token") -> list[dict]:
        return self._get(
            f"/artists/{artist_id}/albums",
            include_groups="album,single", limit=limit, market=market,
        ).get("items", [])

    def album_tracks(self, album_id: str, limit: int = 50) -> list[dict]:
        return self._get(f"/albums/{album_id}/tracks", limit=limit).get("items", [])

    def search_track(self, query: str, limit: int = 3) -> list[dict]:
        return self._get("/search", q=query, type="track", limit=limit).get(
            "tracks", {}).get("items", [])

    def album(self, album_id: str) -> dict:
        """Álbum completo, con tracks (incluye duration_ms por pista)."""
        return self._get(f"/albums/{album_id}", market="from_token")

    def search_album(self, query: str, limit: int = 3) -> list[dict]:
        return self._get("/search", q=query, type="album", limit=limit).get(
            "albums", {}).get("items", [])

    def search_artist(self, query: str, limit: int = 3) -> list[dict]:
        return self._get("/search", q=query, type="artist", limit=limit).get(
            "artists", {}).get("items", [])

    def create_playlist(self, name: str, description: str, uris: list[str],
                        public: bool = False) -> dict:
        user_id = self.me()["id"]
        playlist = self._request(
            "POST", f"/users/{user_id}/playlists",
            json={"name": name, "description": description, "public": public},
        )
        for i in range(0, len(uris), 100):
            self._request(
                "POST", f"/playlists/{playlist['id']}/tracks",
                json={"uris": uris[i:i + 100]},
            )
        return playlist
