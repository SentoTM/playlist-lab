"""setlist.fm: qué tocan de verdad los grupos en directo.

API gratuita para uso no comercial con clave (SETLISTFM_API_KEY). Límites:
unas 2 peticiones por segundo y 1.440 al día; aquí se va a 1/s y se cachea.
Condición de uso: citar a setlist.fm como fuente (van los enlaces).
"""
import logging
import os
import threading
import time

import httpx

log = logging.getLogger("playlist_lab.setlistfm")
API = "https://api.setlist.fm/rest/1.0"


class SetlistfmClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("SETLISTFM_API_KEY", "")
        self._http = httpx.Client(timeout=20)
        self._lock = threading.Lock()
        self._ultima = 0.0

    @property
    def disponible(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, **params) -> dict:
        with self._lock:
            espera = 1.05 - (time.monotonic() - self._ultima)
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()
        resp = self._http.get(f"{API}{path}", params=params, headers={
            "x-api-key": self.api_key, "Accept": "application/json",
            "Accept-Language": "es"})
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()

    def setlists_de(self, mbid: str, paginas: int = 2) -> list[dict]:
        """Setlists de un artista (por su id de MusicBrainz), del más nuevo
        al más viejo. 20 por página."""
        out = []
        for p in range(1, paginas + 1):
            data = self._get(f"/artist/{mbid}/setlists", p=p)
            lote = data.get("setlist") or []
            out.extend(lote)
            if len(lote) < 20:
                break
        return out
