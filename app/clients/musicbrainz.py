"""Cliente de MusicBrainz: verificación de hechos.

API pública, sin clave; solo exige un User-Agent identificable y como mucho
una petición por segundo. Sirve para confirmar lo que un modelo de lenguaje
tiende a inventarse con aplomo: año exacto de publicación, sello, país,
formación de un grupo y discografía real.
"""
import threading
import time

import httpx

API = "https://musicbrainz.org/ws/2"
HEADERS = {"User-Agent": "playlist-lab/0.2 (uso personal; https://github.com/SentoTM/playlist-lab)",
           "Accept": "application/json"}


class MusicbrainzClient:
    def __init__(self):
        self._http = httpx.Client(timeout=20, headers=HEADERS)
        self._lock = threading.Lock()
        self._last = 0.0

    def _get(self, path: str, **params) -> dict:
        """GET con el rate limit de 1 req/s que pide MusicBrainz."""
        with self._lock:
            wait = 1.05 - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        try:
            resp = self._http.get(f"{API}{path}", params={"fmt": "json", **params})
            if resp.status_code != 200:
                return {}
            return resp.json()
        except httpx.HTTPError:
            return {}

    def find_artist(self, name: str) -> dict | None:
        """Artista: país, años de actividad, tipo y etiquetas de la comunidad."""
        data = self._get("/artist", query=f'artist:"{name}"', limit=3)
        for a in data.get("artists", []):
            if a.get("score", 0) < 80:
                continue
            span = a.get("life-span") or {}
            return {
                "artist": a.get("name"),
                "disambiguation": a.get("disambiguation"),
                "type": a.get("type"),
                "country": a.get("country"),
                "activo_desde": span.get("begin"),
                "activo_hasta": span.get("end"),
                "separado": bool(span.get("ended")),
                "tags": [t["name"] for t in (a.get("tags") or [])[:8]],
                "mbid": a.get("id"),
            }
        return None

    def find_release(self, artist: str, album: str) -> dict | None:
        """Álbum: primera publicación real (no la reedición), sello y formato."""
        data = self._get("/release-group",
                         query=f'releasegroup:"{album}" AND artist:"{artist}"', limit=3)
        for rg in data.get("release-groups", []):
            if rg.get("score", 0) < 80:
                continue
            return {
                "album": rg.get("title"),
                "artist": ", ".join(c["name"] for c in (rg.get("artist-credit") or [])
                                    if isinstance(c, dict) and c.get("name")),
                "primera_publicacion": rg.get("first-release-date"),
                "tipo": rg.get("primary-type"),
                "subtipos": rg.get("secondary-types") or [],
                "mbid": rg.get("id"),
            }
        return None

    def discography(self, artist: str, limit: int = 50) -> list[dict]:
        """Álbumes de estudio del artista, por fecha. Detecta huecos y rarezas."""
        a = self.find_artist(artist)
        if not a:
            return []
        data = self._get("/release-group", artist=a["mbid"],
                         type="album", limit=limit)
        out = []
        for rg in data.get("release-groups", []):
            if rg.get("secondary-types"):  # fuera recopilatorios, directos, remixes
                continue
            out.append({"album": rg.get("title"),
                        "fecha": rg.get("first-release-date"),
                        "tipo": rg.get("primary-type")})
        out.sort(key=lambda r: r["fecha"] or "9999")
        return out
